"""Pipeline orquestrador: classify → extract → format → validate → export.

Roda em thread background. Suporta PDFs com múltiplas demonstrações.
Roteia entre Gemini e Anthropic conforme o modelo selecionado em cada etapa.
Formatação feita em Python (sem chamada de IA) para máxima velocidade.
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
import threading
import time
from pathlib import Path

from app.config import GEMINI_API_KEY, ANTHROPIC_API_KEY, ADOBE_CLIENT_ID, ADOBE_CLIENT_SECRET
from app.jobs import Job, JobProgress
from app.services.classifier import classificar
from app.services.gemini_client import (
    extrair_balancete, extrair_demonstracao,
)
from app.services.anthropic_client import (
    extrair_balancete_anthropic, extrair_demonstracao_anthropic,
)
from app.services.formatter import (
    formatar_dre, formatar_balanco, formatar_balancete,
    formatar_dre_multi, formatar_balanco_multi,
)
from app.services.validator import validate
from app.services.exporter import export_excel_multi, export_csv, export_raw_excel, export_raw_csv
from app.services.adobe_ocr import has_native_text, ocr_with_adobe

logger = logging.getLogger("planilhador")

MAX_WORKERS = 10
# Limita classificações simultâneas para evitar respostas truncadas da API
_classify_semaphore = threading.Semaphore(5)


def _api_key_for(model: str | None) -> str:
    """Retorna a API key correta para o modelo."""
    if model and model.startswith("claude-"):
        return ANTHROPIC_API_KEY
    return GEMINI_API_KEY


def process_job(job: Job) -> None:
    """Processa todos os arquivos de um job em paralelo com fila gerenciada.

    Roda em thread background via run_in_executor.
    Usa ThreadPoolExecutor com fila controlada para permitir
    reordenação e cancelamento em tempo real.
    """
    done_event = threading.Event()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)

    try:
        # Inicializa a fila com todos os índices
        with job.queue_lock:
            job.queue = list(range(len(job.files)))
            job.active_count = 0
            job.file_results = []

        def _process_one(idx: int) -> None:
            file_info = job.files[idx]
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

            with job.queue_lock:
                job.completed += 1
                job.active_count -= 1
                _submit_next()

        def _submit_next() -> None:
            """Submete próximos da fila. Deve ser chamado com queue_lock."""
            while job.queue and job.active_count < MAX_WORKERS:
                idx = job.queue.pop(0)
                # Pula cancelados
                if job.progress[idx].status == "cancelled":
                    job.completed += 1
                    continue
                job.active_count += 1
                pool.submit(_process_one, idx)

            # Se não há mais nada rodando nem na fila, sinaliza fim
            if job.active_count == 0 and not job.queue:
                done_event.set()

        # Dispara lote inicial
        with job.queue_lock:
            _submit_next()

        # Aguarda todos terminarem
        done_event.wait()

        # --- Consolidação: Excel multi-aba com todos os períodos ---
        if not job.skip_format and len(job.file_results) > 1:
            try:
                _consolidate_excel(job)
            except Exception as exc:
                logger.warning("Erro ao gerar Excel consolidado: %s", exc)

        job.status = "done"
        logger.info("Job %s concluído: %d arquivos.", job.id, job.total)

    except Exception as exc:
        logger.exception("Erro no job %s: %s", job.id, exc)
        job.status = "error"
        job.error = str(exc)[:500]
    finally:
        pool.shutdown(wait=False)


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

    # Modelos configurados pelo usuário
    classifier_model = job.models.get("classifier")
    extractor_model = job.models.get("extractor")

    is_anthropic_extractor = extractor_model and extractor_model.startswith("claude-")

    # --- ETAPA 1: Classificação (com semáforo para limitar concorrência) ---
    progress.stage = "classifying"
    progress.stage_detail = "Identificando demonstrações..."
    logger.info("[%s] Classificando com %s...", file_info.name, classifier_model)

    with _classify_semaphore:
        classificacao = classificar(
            pdf_path, api_key=_api_key_for(classifier_model), model=classifier_model
        )
    demonstracoes = classificacao.get("demonstracoes", [])
    empresa = classificacao.get("empresa", "")
    custo_total += classificacao.get("custo_usd", 0)

    if not demonstracoes:
        raise ValueError("Nenhuma demonstração financeira reconhecida no PDF.")

    tipos = [d["tipo"] for d in demonstracoes]
    logger.info(
        "[%s] %d demonstração(ões): %s", file_info.name, len(demonstracoes), tipos
    )

    # --- ETAPA 1.5: Adobe OCR para PDFs escaneados ---
    if not has_native_text(pdf_path):
        if ADOBE_CLIENT_ID and ADOBE_CLIENT_SECRET:
            progress.stage_detail = "PDF escaneado detectado. Aplicando Adobe OCR (PT-BR)..."
            logger.info("[%s] PDF sem texto nativo. Aplicando Adobe OCR...", file_info.name)
            try:
                ocr_with_adobe(pdf_path, ADOBE_CLIENT_ID, ADOBE_CLIENT_SECRET)
                logger.info("[%s] Adobe OCR concluído.", file_info.name)
            except Exception as exc:
                logger.warning("[%s] Adobe OCR falhou: %s", file_info.name, exc)
        else:
            logger.warning("[%s] PDF sem texto nativo e sem credenciais Adobe OCR.", file_info.name)

    # --- ETAPA 2+3: Extração + Formatação por demonstração ---
    resultados = []
    todas_observacoes = []

    for i, demo in enumerate(demonstracoes, 1):
        tipo = demo["tipo"]
        paginas = demo.get("paginas")
        periodo = demo.get("periodo", "")

        # --- ETAPA 2: Extração ---
        progress.stage = "extracting"
        progress.stage_detail = f"Extraindo {tipo} ({i}/{len(demonstracoes)})"
        logger.info(
            "[%s] Extraindo %s com %s (páginas: %s)...",
            file_info.name, tipo, extractor_model, paginas,
        )

        def on_extract_progress(detail: str):
            progress.stage_detail = detail

        if tipo == "balancete":
            if is_anthropic_extractor:
                extract_result = extrair_balancete_anthropic(
                    pdf_path, paginas=paginas,
                    model=extractor_model,
                    api_key=ANTHROPIC_API_KEY,
                    on_progress=on_extract_progress,
                )
            else:
                extract_result = extrair_balancete(
                    pdf_path, paginas=paginas,
                    api_key=GEMINI_API_KEY,
                    on_progress=on_extract_progress,
                    model=extractor_model,
                )
        else:
            if is_anthropic_extractor:
                extract_result = extrair_demonstracao_anthropic(
                    pdf_path, tipo, paginas=paginas,
                    model=extractor_model,
                    api_key=ANTHROPIC_API_KEY,
                    on_progress=on_extract_progress,
                )
            else:
                extract_result = extrair_demonstracao(
                    pdf_path, tipo, paginas=paginas,
                    api_key=GEMINI_API_KEY,
                    on_progress=on_extract_progress,
                    model=extractor_model,
                )

        custo_total += extract_result.custo_usd

        if not extract_result.success:
            todas_observacoes.append(f"[{tipo}] Extração falhou: {extract_result.error}")
            continue

        if job.skip_format:
            # Modo "Sem formatação": pula formatação e validação
            resultados.append({
                "tipo": tipo,
                "periodo": periodo,
                "raw_text": extract_result.text,
            })
            continue

        # --- ETAPA 3: Formatação (Python, sem IA) ---
        # Usa funções _multi para DRE/Balanço (detectam multi-período automaticamente)
        progress.stage = "formatting"
        progress.stage_detail = f"Formatando {tipo} ({i}/{len(demonstracoes)})"
        logger.info("[%s] Formatando %s (Python)...", file_info.name, tipo)

        if tipo == "balancete":
            dados_list = [formatar_balancete(extract_result.text, empresa=empresa, periodo=periodo)]
        elif tipo == "dre":
            dados_list = formatar_dre_multi(extract_result.text, empresa=empresa, periodo=periodo)
        elif tipo == "balanco_patrimonial":
            dados_list = formatar_balanco_multi(extract_result.text, empresa=empresa, data_ref=periodo)
        else:
            dados_list = [{"empresa": empresa, "periodo": periodo}]

        # --- ETAPA 4: Validação (para cada período detectado) ---
        for dados in dados_list:
            dados["empresa"] = empresa
            periodo_used = dados.get("periodo", dados.get("data_referencia", periodo))

            progress.stage = "validating"
            progress.stage_detail = f"Validando {tipo} ({periodo_used})"
            logger.info("[%s] Validando %s (%s)...", file_info.name, tipo, periodo_used)

            validacao = validate(dados, tipo)

            if not validacao.passed:
                logger.warning(
                    "[%s] Validação de %s (%s) falhou: %s",
                    file_info.name, tipo, periodo_used, validacao.errors,
                )
                todas_observacoes.extend(
                    [f"[{tipo} {periodo_used}] {e}" for e in validacao.errors]
                )

            todas_observacoes.extend(
                [f"[{tipo} {periodo_used}] {w}" for w in validacao.warnings]
            )

            resultados.append({
                "tipo": tipo,
                "periodo": periodo_used,
                "dados": dados,
                "validacao_ok": validacao.passed,
            })

    if not resultados:
        raise ValueError("Nenhuma demonstração foi extraída com sucesso.")

    # --- ETAPA 5: Exportação ---
    progress.stage = "exporting"
    progress.stage_detail = "Gerando arquivos..."
    logger.info("[%s] Exportando...", file_info.name)

    if job.skip_format:
        # Exporta extração bruta como Excel + CSV
        xlsx_path = output_dir / f"{base_name}.xlsx"
        export_raw_excel(resultados, empresa, xlsx_path)
        progress.output_files.append(xlsx_path.name)

        for r in resultados:
            csv_name = f"{base_name}_{r['tipo']}.csv"
            csv_path = output_dir / csv_name
            export_raw_csv(r["raw_text"], csv_path)
            progress.output_files.append(csv_name)
    else:
        xlsx_path = output_dir / f"{base_name}.xlsx"
        export_excel_multi(resultados, empresa, xlsx_path)
        progress.output_files.append(xlsx_path.name)

        tipo_counts: dict[str, int] = {}
        for r in resultados:
            t = r["tipo"]
            tipo_counts[t] = tipo_counts.get(t, 0) + 1
            if tipo_counts[t] > 1:
                # Multi-período: adiciona período ao nome para evitar colisão
                safe_period = re.sub(r'[/\\:*?"<>|]', '-', r.get("periodo", "")) or str(tipo_counts[t])
                csv_name = f"{base_name}_{t}_{safe_period}.csv"
            else:
                csv_name = f"{base_name}_{t}.csv"
            csv_path = output_dir / csv_name
            export_csv(r["dados"], r["tipo"], csv_path)
            progress.output_files.append(csv_name)

    progress.cost = round(custo_total, 6)

    # Guarda resultados formatados para consolidação multi-aba
    if not job.skip_format and resultados:
        with job.queue_lock:
            job.file_results.append({
                "filename": file_info.name,
                "empresa": empresa,
                "resultados": resultados,
            })

    logger.info(
        "[%s] Concluído: %d demonstração(ões), custo=$%.6f",
        file_info.name, len(resultados), custo_total,
    )


def _consolidate_excel(job: Job) -> None:
    """Gera Excel consolidado com uma aba por período (todos os arquivos)."""
    output_dir = job.output_dir
    # Ordena por nome do arquivo para manter ordem cronológica
    sorted_results = sorted(job.file_results, key=lambda r: r["filename"])

    all_demos = []
    empresa = ""
    for fr in sorted_results:
        empresa = empresa or fr["empresa"]
        for r in fr["resultados"]:
            all_demos.append(r)

    if not all_demos:
        return

    consolidated_path = output_dir / "Consolidado.xlsx"
    export_excel_multi(all_demos, empresa, consolidated_path)
    logger.info(
        "Excel consolidado gerado: %s (%d abas)",
        consolidated_path, len(all_demos),
    )
