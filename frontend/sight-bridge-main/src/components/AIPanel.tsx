import { useCallback, useState, useEffect, useRef } from "react";
import {
  Brain,
  Target,
  Eye,
  Activity,
  Loader2,
  Play,
  AlertTriangle,
  CheckCircle2,
  FileText,
  Plus,
  MessageSquare,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import type {
  AnalysisResult,
  DoctorNote,
  DRModelResult,
  MedicalReport,
  SelectedDRClassification,
} from "@/lib/exam-api";
import type { EyeSide, PerEyeAnalysis } from "@/lib/exam-api";
import {
  runAIAnalysis,
  generateReport,
  fetchDoctorNotes,
  createDoctorNote,
  fetchAnalysis,
  fetchMedicalReports,
} from "@/lib/exam-api";
import { RichTextEditor } from "@/components/RichTextEditor";

interface AIPanelProps {
  studyInstanceUid?: string;
  seriesInstanceUid?: string;
  patientId?: string;
  patientAge?: number;
  examinationId?: string;
  autoRun?: boolean;
  qualityCategory?: "good" | "acceptable" | "bad";
  qualityScore?: number | null;
  imageQualityResults?: Array<{
    score: number;
    category: "good" | "acceptable" | "bad";
  }>;
}

const EYE_SIDES = ["right", "left"] as const;
const DR_LABELS: Record<string, string> = {
  no_dr: "No DR",
  "no dr": "No DR",
  mild_npdr: "Mild NPDR",
  "mild npdr": "Mild NPDR",
  moderate_npdr: "Moderate NPDR",
  "moderate npdr": "Moderate NPDR",
  severe_npdr: "Severe NPDR",
  "severe npdr": "Severe NPDR",
  proliferative_dr: "Proliferative DR",
  "proliferative dr": "Proliferative DR",
};
const DR_ORDER = ["no_dr", "mild_npdr", "moderate_npdr", "severe_npdr", "proliferative_dr"];
const DR_MODEL_ORDER = ["vit", "clip_dr", "flair"] as const;
const DR_MODEL_NAMES: Record<(typeof DR_MODEL_ORDER)[number], string> = {
  vit: "ViT actuel",
  clip_dr: "CLIP-DR",
  flair: "FLAIR (zéro-shot)",
};

function getDRGradeIndex(result: DRModelResult) {
  if (result.grade_index != null && result.grade_index >= 0 && result.grade_index <= 4) {
    return result.grade_index;
  }
  const normalized = result.grade.trim().toLowerCase().replace(/[_-]/g, " ");
  if (normalized.includes("proliferative")) return 4;
  if (normalized.includes("severe")) return 3;
  if (normalized.includes("moderate")) return 2;
  if (normalized.includes("mild")) return 1;
  if (normalized.includes("no dr") || normalized.includes("normal")) return 0;
  return -1;
}

function selectCriticalDR(
  models: Array<{ key: (typeof DR_MODEL_ORDER)[number]; result: DRModelResult }>,
): SelectedDRClassification | null {
  const available = models
    .map((model, priority) => ({
      ...model,
      priority,
      gradeIndex: getDRGradeIndex(model.result),
    }))
    .filter((model) => model.result.status === "ok" && model.gradeIndex >= 0);
  if (available.length === 0) return null;

  available.sort((a, b) =>
    b.gradeIndex - a.gradeIndex
    || Number(b.result.confidence || 0) - Number(a.result.confidence || 0)
    || a.priority - b.priority,
  );
  const selected = available[0];
  const indexes = available.map((model) => model.gradeIndex);
  const spread = Math.max(...indexes) - Math.min(...indexes);
  return {
    ...selected.result,
    model_key: selected.key,
    model_name: DR_MODEL_NAMES[selected.key],
    grade_index: selected.gradeIndex,
    selection_method: "highest_predicted_grade_then_confidence",
    model_grade_spread: spread,
    requires_review: spread >= 2,
  };
}

function formatDRLabel(label: string) {
  const key = label.trim().toLowerCase();
  return DR_LABELS[key] ?? label.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function normalizeDRProbabilities(probabilities: AnalysisResult["dr_classification"]["probabilities"] | undefined) {
  if (!probabilities) return [];
  const rows = Array.isArray(probabilities)
    ? probabilities.map((item) => ({ label: item.label, score: Number(item.score) || 0 }))
    : Object.entries(probabilities).map(([label, score]) => ({ label, score: Number(score) || 0 }));

  const order = new Map(DR_ORDER.map((label, index) => [label, index]));
  return rows
    .map((item) => ({ ...item, displayLabel: formatDRLabel(item.label) }))
    .sort((a, b) => {
      const ai = order.get(a.label.toLowerCase()) ?? Number.MAX_SAFE_INTEGER;
      const bi = order.get(b.label.toLowerCase()) ?? Number.MAX_SAFE_INTEGER;
      return ai - bi;
    });
}

function getReportContent(report: MedicalReport) {
  return report.final_content || report.doctor_content || report.ai_content || "";
}

function toReportHtml(content: string) {
  if (/<(h[1-6]|p|ul|ol|li|br|strong|b|em|i|u|div|section)\b/i.test(content)) {
    return content;
  }
  return content.replace(/\n/g, "<br>");
}

function stripHtml(content: string) {
  if (typeof document === "undefined") return content.replace(/<[^>]+>/g, " ");
  const element = document.createElement("div");
  element.innerHTML = content;
  return element.textContent || element.innerText || "";
}

export function AIPanel({
  studyInstanceUid,
  seriesInstanceUid,
  patientId,
  patientAge,
  examinationId,
  autoRun = false,
  qualityCategory,
  qualityScore,
  imageQualityResults = [],
}: AIPanelProps) {
  const rejectedImageCount = imageQualityResults.filter(
    (result) => result.category === "bad" || result.score < 40,
  ).length;
  const acceptedImageCount = imageQualityResults.length - rejectedImageCount;
  const hasDetailedQuality = imageQualityResults.length > 0;
  const isPoorQuality = hasDetailedQuality
    ? acceptedImageCount === 0
    : qualityCategory === "bad" || (qualityScore != null && qualityScore < 40);
  const qualityBlockMessage = isPoorQuality
    ? "L’analyse IA est désactivée : toutes les images doivent être refaites."
    : rejectedImageCount > 0
      ? `${acceptedImageCount} image(s) envoyée(s) à l’IA. ${rejectedImageCount} image(s) à refaire par le technicien.`
      : null;
  const [analysis, setAnalysis] = useState<AnalysisResult | PerEyeAnalysis | null>(null);
  const [activeEye, setActiveEye] = useState<EyeSide>("right");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportText, setReportText] = useState<string | null>(null);
  const [reportHtml, setReportHtml] = useState<string | null>(null);
  const [reportByEye, setReportByEye] = useState<Partial<Record<EyeSide, string>>>({});
  const [reportHtmlByEye, setReportHtmlByEye] = useState<Partial<Record<EyeSide, string>>>({});
  const [pollingAnalysis, setPollingAnalysis] = useState(false);
  const [generatingReport, setGeneratingReport] = useState(false);
  const [noteInput, setNoteInput] = useState("");
  const [eyeRight, setEyeRight] = useState(false);
  const [eyeLeft, setEyeLeft] = useState(false);
  const [doctorNotes, setDoctorNotes] = useState<DoctorNote[]>([]);
  const [loadingNotes, setLoadingNotes] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const [notesError, setNotesError] = useState<string | null>(null);
  const [showOtherDRModels, setShowOtherDRModels] = useState<Record<EyeSide, boolean>>({
    right: false,
    left: false,
  });

  const eyeAnalysis = isPerEyeAnalysis(analysis) ? analysis : null;
  const activeAnalysis =
    eyeAnalysis
      ? eyeAnalysis[activeEye] ?? null
      : (analysis as AnalysisResult | null);
  const activeReportText = eyeAnalysis ? reportByEye[activeEye] ?? null : reportText;
  const activeReportHtml = eyeAnalysis ? reportHtmlByEye[activeEye] ?? null : reportHtml;
  const clipDR = activeAnalysis
    ? activeAnalysis.dr_classification_models?.clip_dr ?? {
        status: activeAnalysis.dr_classification.grade === "Unknown" ? "unavailable" : "ok",
        ...activeAnalysis.dr_classification,
      }
    : null;
  const vitDR = activeAnalysis
    ? activeAnalysis.dr_classification_models?.vit ?? {
        status: activeAnalysis.dr_classification.grade === "Unknown" ? "unavailable" : "ok",
        ...activeAnalysis.dr_classification,
      }
    : null;
  const flairDR = activeAnalysis?.dr_classification_models?.flair ?? null;
  const drModels = activeAnalysis ? [
    {
      key: "vit" as const,
      result: vitDR ?? {
        status: "unavailable" as const,
        grade: "Unknown",
        confidence: 0,
        probabilities: [],
        calibration_status: "not_locally_calibrated",
        reason: "Résultat ViT absent de cette analyse",
      },
    },
    {
      key: "clip_dr" as const,
      result: clipDR ?? {
        status: "unavailable" as const,
        grade: "Unknown",
        confidence: 0,
        probabilities: [],
        calibration_status: "not_locally_calibrated",
        reason: "Résultat CLIP-DR absent de cette analyse",
      },
    },
    {
      key: "flair" as const,
      result: flairDR ?? {
        status: "unavailable" as const,
        grade: "Unknown",
        confidence: 0,
        probabilities: [],
        calibration_status: "not_locally_calibrated",
        reason: "Résultat FLAIR absent de cette analyse",
      },
    },
  ] : [];
  const fallbackSelectedDR = selectCriticalDR(drModels);
  const persistedSelectedDR = activeAnalysis?.selected_dr_classification;
  const selectedDR = persistedSelectedDR
    && drModels.some((model) => model.key === persistedSelectedDR.model_key)
    ? persistedSelectedDR
    : fallbackSelectedDR;
  const selectedModel = selectedDR
    ? drModels.find((model) => model.key === selectedDR.model_key)
    : null;
  const otherDRModels = selectedModel
    ? drModels.filter((model) => model.key !== selectedModel.key)
    : drModels;
  const hasMultipleAvailableDRModels = drModels.filter(
    (model) => model.result.status === "ok",
  ).length > 1;

  const loadMedicalReport = useCallback(async () => {
    if (!examinationId) return;
    const reports = await fetchMedicalReports(examinationId.replace(/^EX-/, ""));
    if (reports.length === 0) return;
    const report = reports[0];
    const content = getReportContent(report);
    if (!content) return;
    const html = toReportHtml(content);
    const text = stripHtml(content);
    const structuredReports = getStructuredEyeReports(report.ai_report_data);
    const splitText = Object.keys(structuredReports.text).length > 0
      ? structuredReports.text
      : splitReportByEye(text);
    setReportText(text);
    setReportHtml(html);
    setReportByEye(splitText);
    setReportHtmlByEye(Object.keys(structuredReports.html).length > 0
      ? structuredReports.html
      : Object.fromEntries(
          Object.entries(splitText).map(([side, value]) => [side, toReportHtml(value)]),
        ) as Partial<Record<EyeSide, string>>);
  }, [examinationId]);

  useEffect(() => {
    if (!studyInstanceUid) return;
    setShowOtherDRModels({ right: false, left: false });
    const requestedStudyUid = studyInstanceUid;
    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function loadSavedAnalysis() {
      attempts += 1;
      setPollingAnalysis(true);
      try {
        const result = await fetchAnalysis(requestedStudyUid);
        if (cancelled) return;
        setAnalysis(result.analysis);
        const eyes = EYE_SIDES.filter((side) => !!result.analysis[side]);
        if (eyes.length > 0) {
          setActiveEye((current) => (result.analysis[current] ? current : eyes[0]));
        }
        setPollingAnalysis(false);
      } catch {
        if (cancelled) return;
        if (attempts < 24) {
          timer = setTimeout(loadSavedAnalysis, 5000);
        } else {
          setPollingAnalysis(false);
        }
      }
    }

    loadSavedAnalysis();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [studyInstanceUid]);

  useEffect(() => {
    loadMedicalReport().catch(() => {
      // Draft report is optional.
    });

    const handleReportUpdate = () => {
      loadMedicalReport().catch(() => {});
    };

    const handleStorage = (event: StorageEvent) => {
      if (event.key === "teleoph.medical-report-updated") handleReportUpdate();
    };

    window.addEventListener("teleoph.medical-report-updated", handleReportUpdate);
    window.addEventListener("storage", handleStorage);
    window.addEventListener("focus", handleReportUpdate);
    return () => {
      window.removeEventListener("teleoph.medical-report-updated", handleReportUpdate);
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener("focus", handleReportUpdate);
    };
  }, [loadMedicalReport]);

  useEffect(() => {
    if (!seriesInstanceUid) return;
    let cancelled = false;
    setLoadingNotes(true);
    setNotesError(null);
    fetchDoctorNotes(seriesInstanceUid)
      .then((data) => {
        if (!cancelled) setDoctorNotes(data);
      })
      .catch((e) => {
        if (!cancelled) setNotesError(e instanceof Error ? e.message : "Erreur de chargement");
      })
      .finally(() => {
        if (!cancelled) setLoadingNotes(false);
      });
    return () => {
      cancelled = true;
    };
  }, [seriesInstanceUid]);

  const autoRunRef = useRef(false);
  useEffect(() => {
    if (autoRun && studyInstanceUid && !isPoorQuality && !autoRunRef.current) {
      autoRunRef.current = true;
      handleRunAnalysis();
    }
  }, [autoRun, studyInstanceUid, isPoorQuality]);

  async function handleRunAnalysis() {
    if (!studyInstanceUid || isPoorQuality) return;
    setLoading(true);
    setError(null);
    setReportText(null);
    setReportHtml(null);
    setReportByEye({});
    setReportHtmlByEye({});
    try {
      const result = await runAIAnalysis(studyInstanceUid);
      setAnalysis(result.analysis);
      if (isPerEyeAnalysis(result.analysis)) {
        const perEyeResult = result.analysis;
        const eyes = EYE_SIDES.filter((side) => !!perEyeResult[side]);
        if (eyes.length > 0) setActiveEye(eyes[0]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "An unknown error occurred");
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerateReport() {
    if (!activeAnalysis) return;
    setGeneratingReport(true);
    setError(null);
    try {
      const eyeLabel = activeEye === "right" ? "Œil droit (OD)" : "Œil gauche (OG)";
      const result = await generateReport(activeAnalysis, patientId ?? studyInstanceUid ?? "inconnu", {
        patientAge,
        eye: eyeLabel,
        studyInstanceUid,
        seriesUid: seriesInstanceUid,
      });
      if (result.status === "queued") {
        setError("Rapport IA mis en file. Il sera affiché dès qu'il est prêt.");
        return;
      }
      if (eyeAnalysis) {
        setReportByEye((prev) => ({ ...prev, [activeEye]: result.report_text || "" }));
        setReportHtmlByEye((prev) => ({
          ...prev,
          [activeEye]: result.report_html || (result.report_text || "").replace(/\n/g, "<br>"),
        }));
      } else {
        setReportText(result.report_text || "");
        setReportHtml(result.report_html || (result.report_text || "").replace(/\n/g, "<br>"));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Report generation failed");
    } finally {
      setGeneratingReport(false);
    }
  }

  async function handleAddNote() {
    const trimmed = noteInput.trim();
    if (!trimmed) return;
    if (!seriesInstanceUid) {
      setNotesError("Aucune série DICOM disponible.");
      return;
    }
    if (!eyeRight && !eyeLeft) {
      setNotesError("Veuillez sélectionner au moins un œil.");
      return;
    }
    const eye = eyeRight && eyeLeft ? "both" : eyeRight ? "right" : "left";
    setSavingNote(true);
    setNotesError(null);
    try {
      const note = await createDoctorNote(seriesInstanceUid, trimmed, eye);
      setDoctorNotes((prev) => [...prev, note]);
      setNoteInput("");
      setEyeRight(false);
      setEyeLeft(false);
    } catch (e) {
      setNotesError(e instanceof Error ? e.message : "Échec de l'enregistrement.");
    } finally {
      setSavingNote(false);
    }
  }

  const hasAnalysis = !!activeAnalysis;

  return (
    <div className="rounded-xl border border-slate-700 bg-[#0A1128] text-slate-200 flex flex-col max-h-[600px]">
      <div className="p-4 border-b border-slate-800 bg-[#0A1128] flex items-center justify-between">
        <h2 className="text-sm font-semibold flex items-center gap-2 text-white">
          <Brain className="h-4 w-4 text-blue-400" />
          AI Analysis Report
        </h2>
      </div>

      <div className="p-5 space-y-5 flex-1 overflow-y-auto custom-scrollbar">
        {!studyInstanceUid && (
          <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 border border-amber-500/30 p-3 text-xs text-amber-300">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>No DICOM study available for AI analysis.</span>
          </div>
        )}

        {isPoorQuality && qualityBlockMessage && (
          <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 border border-amber-500/30 p-3 text-xs text-amber-300">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{qualityBlockMessage}</span>
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 rounded-lg bg-red-500/10 border border-red-500/30 p-3 text-xs text-red-300">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {!hasAnalysis && !loading && !pollingAnalysis && !error && studyInstanceUid && (
          <div className="flex flex-col items-center gap-3 py-8 text-center">
            <Brain className="h-8 w-8 text-slate-600" />
            <p className="text-xs text-slate-500 max-w-[200px]">
              Press &quot;Run AI Analysis&quot; below to process this exam with the AI model.
            </p>
          </div>
        )}

        {(loading || pollingAnalysis) && !activeAnalysis && (
          <div className="flex flex-col items-center gap-3 py-8 text-center">
            <Loader2 className="h-8 w-8 text-blue-400 animate-spin" />
            <p className="text-xs text-slate-400">
              {loading
                ? "Running AI analysis… this may take up to 5 minutes."
                : "Classification automatique en cours…"}
            </p>
          </div>
        )}

        {studyInstanceUid && (
          <div className="grid grid-cols-2 gap-2">
            {EYE_SIDES.map((side) => {
              const isActive = activeEye === side;
              const isReady = !eyeAnalysis || !!eyeAnalysis[side];
              return (
                <button
                  key={side}
                  type="button"
                  onClick={() => setActiveEye(side)}
                  className={`min-h-9 rounded-md border px-2 text-xs font-semibold transition ${
                    isActive
                      ? "border-cyan-300 bg-cyan-500/15 text-cyan-100 shadow-[0_0_12px_rgba(34,211,238,0.45)]"
                      : "border-slate-600 bg-slate-700/50 text-slate-200 hover:border-slate-400"
                  }`}
                >
                  <span className="inline-flex items-center justify-center gap-1.5">
                    {!isReady && pollingAnalysis && <Loader2 className="h-3 w-3 animate-spin" />}
                    [ {side === "right" ? "Œil droit" : "Œil gauche"} ]
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {!activeAnalysis && eyeAnalysis && (
          <div className="flex flex-col items-center gap-3 rounded-lg border border-slate-700 bg-[#121936] px-4 py-8 text-center">
            <Loader2 className="h-7 w-7 text-cyan-300 animate-spin" />
            <p className="text-xs text-slate-400">
              Résultat {activeEye === "right" ? "œil droit" : "œil gauche"} en attente…
            </p>
          </div>
        )}

        {activeAnalysis && (
          <>

            {/* DR Classification */}
            <section className="space-y-2">
              <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
                <Activity className="h-3.5 w-3.5 text-emerald-400" />
                Classification RD — résultat le plus critique
              </h3>
              <div className="grid grid-cols-1 gap-2">
                {selectedModel ? (
                  <>
                    <DRResultCard
                      title={DR_MODEL_NAMES[selectedModel.key]}
                      canonical
                      result={selectedModel.result}
                    />
                    <p className="px-1 text-[10px] text-slate-400">
                      Sélection conservatrice : grade maximal prédit parmi les modèles.
                    </p>
                    {selectedDR?.requires_review && (
                      <div className="flex items-start gap-1.5 rounded-md border border-amber-700/70 bg-amber-950/30 p-2 text-[10px] text-amber-300">
                        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                        Désaccord important entre les modèles — validation ophtalmologique requise.
                      </div>
                    )}
                    {hasMultipleAvailableDRModels && otherDRModels.length > 0 && (
                      <button
                        type="button"
                        onClick={() => setShowOtherDRModels((current) => ({
                          ...current,
                          [activeEye]: !current[activeEye],
                        }))}
                        aria-expanded={showOtherDRModels[activeEye]}
                        className="flex w-full items-center justify-center gap-1.5 rounded-md border border-cyan-700/70 bg-cyan-950/20 px-3 py-2 text-xs font-medium text-cyan-300 transition-colors hover:bg-cyan-900/30"
                      >
                        {showOtherDRModels[activeEye] ? (
                          <>
                            <ChevronUp className="h-3.5 w-3.5" />
                            Masquer les résultats des autres modèles
                          </>
                        ) : (
                          <>
                            <ChevronDown className="h-3.5 w-3.5" />
                            Voir les résultats des autres modèles ({otherDRModels.length})
                          </>
                        )}
                      </button>
                    )}
                    {hasMultipleAvailableDRModels && showOtherDRModels[activeEye] && otherDRModels.map((model) => (
                      <DRResultCard
                        key={model.key}
                        title={DR_MODEL_NAMES[model.key]}
                        result={model.result}
                      />
                    ))}
                  </>
                ) : (
                  <div className="rounded-lg border border-amber-700/70 bg-amber-950/20 p-3 text-xs text-amber-300">
                    Classification indisponible
                  </div>
                )}
              </div>
            </section>

            {/* Lesions */}
            <section className="space-y-2">
              <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
                <Target className="h-3.5 w-3.5 text-amber-400" />
                Lesions
              </h3>
              <div className="rounded-lg bg-[#121936] border border-slate-700 p-3 space-y-2">
                <LesionRow label="Microaneurysms" value={activeAnalysis.lesions.microaneurysms} />
                <LesionRow label="Hemorrhages" value={activeAnalysis.lesions.hemorrhages} />
                <LesionRow
                  label="Hard exudates"
                  value={activeAnalysis.lesions.hard_exudates ?? activeAnalysis.lesions.exudates}
                />
                <LesionRow
                  label="Cotton-wool spots"
                  value={activeAnalysis.lesions.soft_exudates ?? activeAnalysis.lesions.cotton_wool_spots ?? 0}
                />
                <LesionRow
                  label="Neovascularization"
                  value={activeAnalysis.lesions.neovascularization ?? 0}
                />
                <div className="flex items-center justify-between pt-1 border-t border-slate-700">
                  <span className="text-xs text-slate-400">Coverage</span>
                  <span className="text-xs text-amber-400 font-mono">
                    {activeAnalysis.lesions.coverage_pct.toFixed(1)}%
                  </span>
                </div>
              </div>
            </section>

            {/* Optic Disc / Cup */}
            <section className="space-y-2">
              <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
                <Eye className="h-3.5 w-3.5 text-purple-400" />
                Optic Disc / Cup
              </h3>
              <div className="rounded-lg bg-[#121936] border border-slate-700 p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">Disc Area</span>
                  <span className="text-xs text-slate-300 font-mono">
                    {activeAnalysis.optic_disc_cup.disc_area_px > 0
                      ? `${activeAnalysis.optic_disc_cup.disc_area_px} px`
                      : "\u2014 px"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">Cup Area</span>
                  <span className="text-xs text-slate-300 font-mono">
                    {activeAnalysis.optic_disc_cup.cup_area_px > 0
                      ? `${activeAnalysis.optic_disc_cup.cup_area_px} px`
                      : "\u2014 px"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">Cup/Disc Ratio</span>
                  <span
                    className={`text-xs font-semibold font-mono ${
                      activeAnalysis.optic_disc_cup.cup_disc_ratio > 0.5
                        ? "text-red-400"
                        : "text-purple-400"
                    }`}
                  >
                    {activeAnalysis.optic_disc_cup.cup_disc_ratio.toFixed(2)}
                  </span>
                </div>
                <div className="flex items-center justify-between pt-1 border-t border-slate-700">
                  <span className="text-xs text-slate-400">Glaucoma Risk</span>
                  <span
                    className={`text-xs font-semibold ${
                      activeAnalysis.glaucoma.risk === "Faible"
                        ? "text-emerald-400"
                        : activeAnalysis.glaucoma.risk === "Modere"
                          ? "text-amber-400"
                          : activeAnalysis.glaucoma.risk === "Eleve" ||
                              activeAnalysis.glaucoma.risk === "Tres eleve"
                            ? "text-red-400"
                            : "text-slate-500"
                    }`}
                  >
                    {activeAnalysis.glaucoma.risk}
                  </span>
                </div>
              </div>
            </section>

            {/* Vessels */}
            <section className="space-y-2">
              <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
                <Activity className="h-3.5 w-3.5 text-cyan-400" />
                Vessels
              </h3>
              <div className="rounded-lg bg-[#121936] border border-slate-700 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">Coverage</span>
                  <span className="text-xs text-cyan-400 font-mono">
                    {activeAnalysis.vessels.coverage_pct.toFixed(1)}%
                  </span>
                </div>
              </div>
            </section>

            {activeAnalysis.fovea && (
              <section className="space-y-2">
                <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
                  <Target className="h-3.5 w-3.5 text-yellow-300" />
                  Fovea
                </h3>
                <div className="rounded-lg bg-[#121936] border border-slate-700 p-3">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-400">Position</span>
                    <span className="font-mono text-yellow-200">
                      ({activeAnalysis.fovea.x_px.toFixed(1)}, {activeAnalysis.fovea.y_px.toFixed(1)}) px
                    </span>
                  </div>
                </div>
              </section>
            )}

            {activeAnalysis.deepseenet_plus && (
              <section className="space-y-2">
                <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
                  <Eye className="h-3.5 w-3.5 text-rose-300" />
                  DMLA — DeepSeeNet+
                </h3>
                <div className="rounded-lg bg-[#121936] border border-slate-700 p-3 space-y-2">
                  {([
                    ["Drusen", activeAnalysis.deepseenet_plus.drusen],
                    ["Pigmentation", activeAnalysis.deepseenet_plus.pigment],
                    ["DMLA avancée", activeAnalysis.deepseenet_plus.amd],
                  ] as const).map(([label, factor]) => factor && (
                    <div key={label} className="flex items-center justify-between gap-3 text-xs">
                      <span className="text-slate-400">{label}</span>
                      <span className="text-rose-200 text-right">
                        {factor.label.replace(/_/g, " ")} ({(factor.probability * 100).toFixed(1)}%)
                      </span>
                    </div>
                  ))}
                  <div className="flex items-center justify-between pt-2 border-t border-slate-700 text-xs">
                    <span className="text-slate-400">Score AREDS bilatéral</span>
                    <span className="font-semibold text-rose-300">
                      {activeAnalysis.deepseenet_plus.patient_summary?.simplified_score == null
                        ? "Non calculable"
                        : `${activeAnalysis.deepseenet_plus.patient_summary.simplified_score}/5`}
                    </span>
                  </div>
                  <div className="flex items-start gap-1.5 pt-1 text-[10px] text-amber-300/80">
                    <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" />
                    Agrégation conservatrice : les facteurs peuvent provenir de plusieurs images.
                  </div>
                </div>
              </section>
            )}

            {/* Grad-CAM */}
            {activeAnalysis.gradcam_image && (
              <section className="space-y-2">
                <h3 className="text-sm font-bold text-white">Grad-CAM</h3>
                <img
                  src={`data:image/png;base64,${activeAnalysis.gradcam_image}`}
                  alt="Grad-CAM"
                  className="w-full rounded-lg border border-slate-700"
                />
              </section>
            )}

            {/* CLAHE */}
            {activeAnalysis.clahe_image && (
              <section className="space-y-2">
                <h3 className="text-sm font-bold text-white">CLAHE Enhanced</h3>
                <img
                  src={`data:image/png;base64,${activeAnalysis.clahe_image}`}
                  alt="CLAHE"
                  className="w-full rounded-lg border border-slate-700"
                />
              </section>
            )}

            <div className="flex items-center gap-1.5 text-[10px] text-emerald-600">
              <CheckCircle2 className="h-3 w-3" />
              Analysis completed
            </div>

            {activeReportText && activeReportHtml && (
              <section className="space-y-2">
                <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5 text-blue-400" />
                  Report {activeEye === "right" ? "Œil droit" : "Œil gauche"}
                </h3>
                <RichTextEditor
                  value={activeReportHtml}
                  onChange={(value) => {
                    if (eyeAnalysis) {
                      setReportHtmlByEye((prev) => ({ ...prev, [activeEye]: value }));
                    } else {
                      setReportHtml(value);
                    }
                  }}
                />
              </section>
            )}

            {generatingReport && (
              <div className="flex flex-col items-center gap-3 py-4 text-center">
                <Loader2 className="h-6 w-6 text-blue-400 animate-spin" />
                <p className="text-xs text-slate-400">Generating clinical report…</p>
              </div>
            )}
          </>
        )}

        {/* Notes */}
        <section className="space-y-3 pt-4 border-t border-slate-700">
          <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
            <MessageSquare className="h-3.5 w-3.5 text-blue-400" />
            Note Médecin
          </h3>

          {notesError && (
            <div className="flex items-start gap-2 rounded-lg bg-red-500/10 border border-red-500/30 p-3 text-xs text-red-300">
              <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
              <span>{notesError}</span>
            </div>
          )}

          {seriesInstanceUid && (
            <>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={eyeRight}
                    onChange={(e) => setEyeRight(e.target.checked)}
                    className="h-4 w-4 rounded border-slate-600 bg-[#121936] text-blue-600 focus:ring-blue-500 focus:ring-offset-0 cursor-pointer"
                  />
                  Œil droit
                </label>
                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={eyeLeft}
                    onChange={(e) => setEyeLeft(e.target.checked)}
                    className="h-4 w-4 rounded border-slate-600 bg-[#121936] text-blue-600 focus:ring-blue-500 focus:ring-offset-0 cursor-pointer"
                  />
                  Œil gauche
                </label>
              </div>

              <div className="flex gap-2">
                <textarea
                  value={noteInput}
                  onChange={(e) => setNoteInput(e.target.value)}
                  placeholder="Écrire une note…"
                  className="flex-1 rounded-md border border-slate-700 bg-[#121936] px-3 py-2 text-xs text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 resize-none"
                  rows={2}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleAddNote();
                    }
                  }}
                />
                <button
                  onClick={handleAddNote}
                  disabled={!noteInput.trim() || savingNote}
                  className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition shrink-0 self-end"
                >
                  {savingNote ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Plus className="h-3.5 w-3.5" />
                  )}
                  {savingNote ? "Enregistrement…" : "Ajouter"}
                </button>
              </div>
            </>
          )}

          {!seriesInstanceUid && (
            <p className="text-xs text-slate-500">Aucune série DICOM disponible pour les notes.</p>
          )}

          {loadingNotes && (
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Loader2 className="h-3 w-3 animate-spin" />
              Chargement des notes…
            </div>
          )}

          {doctorNotes.length > 0 && (
            <ul className="space-y-2">
              {doctorNotes.map((note) => (
                <li key={note.id} className="rounded-lg bg-[#121936] border border-slate-700 p-3">
                  <div className="flex items-center justify-between mb-1">
                    <span
                      className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${
                        note.eye === "right"
                          ? "bg-blue-500/20 text-blue-300"
                          : note.eye === "left"
                            ? "bg-purple-500/20 text-purple-300"
                            : "bg-emerald-500/20 text-emerald-300"
                      }`}
                    >
                      {note.eye === "right"
                        ? "Œil droit"
                        : note.eye === "left"
                          ? "Œil gauche"
                          : "Les deux"}
                    </span>
                    <span className="text-[10px] text-slate-500">
                      {note.user_name && <span className="mr-2">{note.user_name}</span>}
                      {new Date(note.created_at).toLocaleDateString("fr-FR", {
                        day: "numeric",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                  <p className="text-xs text-slate-300 whitespace-pre-wrap">{note.text}</p>
                </li>
              ))}
            </ul>
          )}
        </section>

        {studyInstanceUid && (
          <div className="flex items-center gap-2 pt-3 border-t border-slate-700">
            <button
              onClick={handleRunAnalysis}
              disabled={loading || generatingReport || isPoorQuality}
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition"
              title={isPoorQuality ? "Analyse IA indisponible pour cette image" : undefined}
            >
              {loading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              {loading ? "Running…" : isPoorQuality ? "IA indisponible" : hasAnalysis ? "Run Analysis Again" : "Run AI Analysis"}
            </button>
            {hasAnalysis && (
              <button
                onClick={handleGenerateReport}
                disabled={loading || generatingReport}
                className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition"
              >
                {generatingReport ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <FileText className="h-3.5 w-3.5" />
                )}
                {generatingReport ? "Generating…" : "Generate Report"}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function LesionRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-slate-400">{label}</span>
      <span className="text-xs text-slate-300 font-mono">{value}</span>
    </div>
  );
}

function DRResultCard({
  title,
  result,
  canonical = false,
}: {
  title: string;
  result: DRModelResult;
  canonical?: boolean;
}) {
  const probabilities = normalizeDRProbabilities(result.probabilities);
  const available = result.status === "ok";
  return (
    <div className="rounded-lg bg-[#121936] border border-slate-700 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-white">{title}</span>
        {canonical && (
          <span className="rounded bg-emerald-950 px-1.5 py-0.5 text-[10px] text-emerald-300">
            canonique
          </span>
        )}
      </div>
      {!available ? (
        <div className="space-y-1 text-xs text-amber-300">
          <div className="flex items-center gap-1">
            <AlertTriangle className="h-3 w-3" />
            Indisponible
          </div>
          {result.reason && <p className="break-words text-[10px] text-slate-400">{result.reason}</p>}
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">Grade prédit</span>
            <span className="text-xs font-semibold text-emerald-400">{formatDRLabel(result.grade)}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">Confiance</span>
            <span className="text-xs text-slate-300">{(result.confidence * 100).toFixed(1)}%</span>
          </div>
          {probabilities.length > 0 && (
            <div className="space-y-2 pt-2 border-t border-slate-700">
              {probabilities.map((probability) => {
                const percentage = Math.max(0, Math.min(100, probability.score * 100));
                const predicted = probability.displayLabel.toLowerCase() === formatDRLabel(result.grade).toLowerCase();
                return (
                  <div key={probability.label} className="grid grid-cols-[82px_1fr_38px] items-center gap-2 text-[10px]">
                    <span className={`truncate ${predicted ? "text-cyan-100" : "text-slate-400"}`}>
                      {probability.displayLabel}
                    </span>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-950/45">
                      <div
                        className={`h-full rounded-full ${predicted ? "bg-cyan-300" : "bg-slate-500"}`}
                        style={{ width: `${percentage}%` }}
                      />
                    </div>
                    <span className="text-right font-mono text-slate-400">{percentage.toFixed(0)}%</span>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
      {result.calibration_status && (
        <p className="border-t border-slate-700 pt-1 text-[10px] text-slate-500">
          Calibration : {result.calibration_status === "not_locally_calibrated"
            ? "non validée localement"
            : result.calibration_status}
        </p>
      )}
    </div>
  );
}

function isPerEyeAnalysis(value: AnalysisResult | PerEyeAnalysis | null): value is PerEyeAnalysis {
  return !!value && ("right" in value || "left" in value);
}

function splitReportByEye(content: string): Partial<Record<EyeSide, string>> {
  const markers: Array<{ side: EyeSide; match: RegExp }> = [
    { side: "right", match: /(?:Œ|Oe)il droit\s*:/i },
    { side: "left", match: /(?:Œ|Oe)il gauche\s*:/i },
  ];
  const found = markers
    .map((marker) => {
      const match = marker.match.exec(content);
      return match ? { side: marker.side, index: match.index, length: match[0].length } : null;
    })
    .filter((item): item is { side: EyeSide; index: number; length: number } => !!item)
    .sort((a, b) => a.index - b.index);

  if (found.length === 0) return {};

  const result: Partial<Record<EyeSide, string>> = {};
  found.forEach((item, idx) => {
    const next = found[idx + 1];
    const text = content.slice(item.index + item.length, next?.index).trim();
    if (text) result[item.side] = text;
  });
  return result;
}

function getStructuredEyeReports(value: unknown): {
  text: Partial<Record<EyeSide, string>>;
  html: Partial<Record<EyeSide, string>>;
} {
  const text: Partial<Record<EyeSide, string>> = {};
  const html: Partial<Record<EyeSide, string>> = {};
  if (!value || typeof value !== "object") return { text, html };

  const reports = (value as { reports_by_eye?: unknown }).reports_by_eye;
  if (!reports || typeof reports !== "object") return { text, html };

  EYE_SIDES.forEach((side) => {
    const report = (reports as Record<string, unknown>)[side];
    if (!report || typeof report !== "object") return;
    const data = report as { report_text?: unknown; report_html?: unknown };
    const reportText = typeof data.report_text === "string" ? data.report_text : "";
    const reportHtml = typeof data.report_html === "string" ? data.report_html : "";
    if (reportText) text[side] = reportText;
    if (reportHtml || reportText) html[side] = reportHtml || toReportHtml(reportText);
  });

  return { text, html };
}
