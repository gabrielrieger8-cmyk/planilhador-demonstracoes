"""Pipeline orquestrador: classify → extract (Gemini) → format (Sonnet) → validate → export.

Roda em thread background. Suporta PDFs com múltiplas demonstrações.

Fluxo:
  Gemini 2.0 Flash (classifica) → Gemini 2.5 Flash (extrai) → Sonnet (formata) → Validação → Excel
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app.config import GEMINI_API_KEY, ANTHROPIC_API_KEY
from app.jobs import Job, JobProgress
from app.services.classifier import classificar
from app.services.gemini_client import extrair_balancete, extrair_demonstracao
from app.services.anthropic_client import formatar_demonstracao, refinar_balancete
from app.services.validator import validate
from app.services.exporter import export_excel_multi, export_csv

logger = logging.getLogger("planilhador")


def process_job(job: Job) -> None:
    """Processa todos os arquivos de um job.

    Roda em thread background via run_in_executor.
    """
    try:
        for idx, file_info in enumerate(job.files):
            progress = job.progress[idx]
            progress.status = "processing"
            start_time = time.time()

            try:
                _process_single_file(file_info, progress, job)
                progress.status = "done"
            except Exception as exc:
                logger.exception("Erro processando %s: %s", file_info.name, exc)
                progress.status = "error"
                progress.error = str(exc)[:500]

            progress.time = round(time.time() - start_time, 2)
            job.completed = idx + 1

        job.status = "done"
        logger.info("Job %s concluído: %d arquivos.", job.id, job.total)

    except Exception as exc:
        logger.exception("Erro no job %s: %s", job.id, exc)
        job.status = "error"
        job.error = str(exc)[:500]


def _process_single_file(
    file_info,
    progress: JobProgress,
    job: Job,
) -> None:
    """Processa um único PDF pelo pipeline completo."""
    pdf_path = str(file_info.path)
    output_dir = job.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = Path(file_info.name).stem
    custo_total = 0.0

    # --- ETAPA 1: Classificação (Gemini 2.0 Flash) ---
    progress.stage = "classifying"
    progress.stage_detail = "Identificando demonstrações..."
    logger.info("[%s] Classificando documento...", file_info.name)

    classificacao = classificar(pdf_path, api_key=GEMINI_API_KEY)
    demonstracoes = classificacao.get("demonstracoes", [])
    empresa = classificacao.get("empresa", "")
    custo_total += classificacao.get("custo_usd", 0)

    if not demonstracoes:
        raise ValueError("Nenhuma demonstração financeira reconhecida no PDF.")

    tipos = [d["tipo"] for d in demonstracoes]
    logger.info(
        "[%s] %d demonstração(ões): %s", file_info.name, len(demonstracoes), tipos
    )

    # --- ETAPA 2+3: Extração (Gemini) + Formatação (Sonnet) por demonstração ---
    resultados = []
    todas_observacoes = []

    for i, demo in enumerate(demonstracoes, 1):
        tipo = demo["tipo"]
        paginas = demo.get("paginas")
        periodo = demo.get("periodo", "")

        # --- ETAPA 2: Extração via Gemini 2.5 Flash ---
        progress.stage = "extracting"
        progress.stage_detail = f"Extraindo {tipo} ({i}/{len(demonstracoes)})"
        logger.info(
            "[%s] Extraindo %s (páginas: %s)...", file_info.name, tipo, paginas
        )

        def on_extract_progress(detail: str):
            progress.stage_detail = detail

        if tipo == "balancete":
            gemini_result = extrair_balancete(
                pdf_path, paginas=paginas,
                api_key=GEMINI_API_KEY,
                on_progress=on_extract_progress,
            )
        else:
            gemini_result = extrair_demonstracao(
                pdf_path, tipo, paginas=paginas,
                api_key=GEMINI_API_KEY,
                on_progress=on_extract_progress,
            )

        custo_total += gemini_result.custo_usd

        if not gemini_result.success:
            todas_observacoes.append(f"[{tipo}] Extração falhou: {gemini_result.error}")
            continue

        # --- ETAPA 3: Formatação via Sonnet ---
        progress.stage = "formatting"
        progress.stage_detail = f"Formatando {tipo} ({i}/{len(demonstracoes)})"
        logger.info("[%s] Formatando %s com Sonnet...", file_info.name, tipo)

        if tipo == "balancete":
            sonnet_result = refinar_balancete(
                gemini_result.text, api_key=ANTHROPIC_API_KEY
            )
        else:
            sonnet_result = formatar_demonstracao(
                gemini_result.text, tipo, api_key=ANTHROPIC_API_KEY
            )

        dados = sonnet_result.get("dados", {})
        custo_total += sonnet_result.get("custo_usd", 0)

        # Enriquece dados
        dados["empresa"] = empresa
        if periodo and "periodo" not in dados:
            dados["periodo"] = periodo

        # --- ETAPA 4: Validação ---
        progress.stage = "validating"
        progress.stage_detail = f"Validando {tipo}"
        logger.info("[%s] Validando %s...", file_info.name, tipo)

        validacao = validate(dados, tipo)

        if not validacao.passed:
            logger.warning(
                "[%s] Validação de %s falhou: %s",
                file_info.name, tipo, validacao.errors,
            )
            todas_observacoes.extend(
                [f"[{tipo}] {e}" for e in validacao.errors]
            )

        todas_observacoes.extend(
            [f"[{tipo}] {w}" for w in validacao.warnings]
        )

        resultados.append({
            "tipo": tipo,
            "periodo": periodo,
            "dados": dados,
            "validacao_ok": validacao.passed,
        })

    if not resultados:
        raise ValueError("Nenhuma demonstração foi extraída com sucesso.")

    # --- ETAPA 5: Exportação ---
    progress.stage = "exporting"
    progress.stage_detail = "Gerando Excel e CSV..."
    logger.info("[%s] Exportando...", file_info.name)

    xlsx_path = output_dir / f"{base_name}.xlsx"
    export_excel_multi(resultados, empresa, xlsx_path)
    progress.output_files.append(xlsx_path.name)

    for r in resultados:
        csv_name = f"{base_name}_{r['tipo']}.csv"
        csv_path = output_dir / csv_name
        export_csv(r["dados"], r["tipo"], csv_path)
        progress.output_files.append(csv_name)

    progress.cost = round(custo_total, 6)

    logger.info(
        "[%s] Concluído: %d demonstração(ões), custo=$%.6f",
        file_info.name, len(resultados), custo_total,
    )
