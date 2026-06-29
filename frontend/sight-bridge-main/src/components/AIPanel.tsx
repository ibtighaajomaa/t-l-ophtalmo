import { useState, useEffect } from "react";
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
} from "lucide-react";
import type { AnalysisResult, DoctorNote } from "@/lib/exam-api";
import { runAIAnalysis, generateReport, fetchDoctorNotes, createDoctorNote } from "@/lib/exam-api";

interface AIPanelProps {
  studyInstanceUid?: string;
  seriesInstanceUid?: string;
  patientId?: string;
}

export function AIPanel({ studyInstanceUid, seriesInstanceUid, patientId }: AIPanelProps) {
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportText, setReportText] = useState<string | null>(null);
  const [generatingReport, setGeneratingReport] = useState(false);
  const [noteInput, setNoteInput] = useState("");
  const [eyeRight, setEyeRight] = useState(false);
  const [eyeLeft, setEyeLeft] = useState(false);
  const [doctorNotes, setDoctorNotes] = useState<DoctorNote[]>([]);
  const [loadingNotes, setLoadingNotes] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const [notesError, setNotesError] = useState<string | null>(null);

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

  async function handleRunAnalysis() {
    if (!studyInstanceUid) return;
    setLoading(true);
    setError(null);
    setReportText(null);
    try {
      const result = await runAIAnalysis(studyInstanceUid);
      setAnalysis(result.analysis);
    } catch (e) {
      setError(e instanceof Error ? e.message : "An unknown error occurred");
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerateReport() {
    if (!analysis) return;
    setGeneratingReport(true);
    setError(null);
    try {
      const result = await generateReport(analysis, patientId ?? studyInstanceUid ?? "inconnu");
      setReportText(result.report_text);
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

  const hasAnalysis = !!analysis;

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

        {error && (
          <div className="flex items-start gap-2 rounded-lg bg-red-500/10 border border-red-500/30 p-3 text-xs text-red-300">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {!hasAnalysis && !loading && !error && studyInstanceUid && (
          <div className="flex flex-col items-center gap-3 py-8 text-center">
            <Brain className="h-8 w-8 text-slate-600" />
            <p className="text-xs text-slate-500 max-w-[200px]">
              Press &quot;Run AI Analysis&quot; below to process this exam with the AI model.
            </p>
          </div>
        )}

        {loading && (
          <div className="flex flex-col items-center gap-3 py-8 text-center">
            <Loader2 className="h-8 w-8 text-blue-400 animate-spin" />
            <p className="text-xs text-slate-400">
              Running AI analysis… this may take up to 5 minutes.
            </p>
          </div>
        )}

        {hasAnalysis && (
          <>
            {/* DR Classification */}
            <section className="space-y-2">
              <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
                <Activity className="h-3.5 w-3.5 text-emerald-400" />
                DR Classification
              </h3>
              <div className="rounded-lg bg-[#121936] border border-slate-700 p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">Predicted Grade</span>
                  <span
                    className={`text-xs font-semibold ${
                      analysis.dr_classification.grade === "Unknown"
                        ? "text-slate-500"
                        : "text-emerald-400"
                    }`}
                  >
                    {analysis.dr_classification.grade}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">Confidence</span>
                  <span className="text-xs text-slate-300">
                    {(analysis.dr_classification.confidence * 100).toFixed(1)}%
                  </span>
                </div>
                {analysis.dr_classification.probabilities.length > 0 && (
                  <div className="space-y-1 pt-1 border-t border-slate-700">
                    {analysis.dr_classification.probabilities.map((p) => (
                      <div key={p.label} className="flex items-center justify-between text-[11px]">
                        <span className="text-slate-500">{p.label}</span>
                        <span className="text-slate-400 font-mono">
                          {(p.score * 100).toFixed(1)}%
                        </span>
                      </div>
                    ))}
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
                <LesionRow label="Microaneurysms" value={analysis.lesions.microaneurysms} />
                <LesionRow label="Hemorrhages" value={analysis.lesions.hemorrhages} />
                <LesionRow label="Exudates" value={analysis.lesions.exudates} />
                <div className="flex items-center justify-between pt-1 border-t border-slate-700">
                  <span className="text-xs text-slate-400">Coverage</span>
                  <span className="text-xs text-amber-400 font-mono">
                    {analysis.lesions.coverage_pct.toFixed(1)}%
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
                    {analysis.optic_disc_cup.disc_area_px > 0
                      ? `${analysis.optic_disc_cup.disc_area_px} px`
                      : "\u2014 px"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">Cup Area</span>
                  <span className="text-xs text-slate-300 font-mono">
                    {analysis.optic_disc_cup.cup_area_px > 0
                      ? `${analysis.optic_disc_cup.cup_area_px} px`
                      : "\u2014 px"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">Cup/Disc Ratio</span>
                  <span
                    className={`text-xs font-semibold font-mono ${
                      analysis.optic_disc_cup.cup_disc_ratio > 0.5
                        ? "text-red-400"
                        : "text-purple-400"
                    }`}
                  >
                    {analysis.optic_disc_cup.cup_disc_ratio.toFixed(2)}
                  </span>
                </div>
                <div className="flex items-center justify-between pt-1 border-t border-slate-700">
                  <span className="text-xs text-slate-400">Glaucoma Risk</span>
                  <span
                    className={`text-xs font-semibold ${
                      analysis.glaucoma.risk === "Faible"
                        ? "text-emerald-400"
                        : analysis.glaucoma.risk === "Modere"
                          ? "text-amber-400"
                          : analysis.glaucoma.risk === "Eleve" ||
                              analysis.glaucoma.risk === "Tres eleve"
                            ? "text-red-400"
                            : "text-slate-500"
                    }`}
                  >
                    {analysis.glaucoma.risk}
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
                    {analysis.vessels.coverage_pct.toFixed(1)}%
                  </span>
                </div>
              </div>
            </section>

            {/* Grad-CAM */}
            {analysis.gradcam_image && (
              <section className="space-y-2">
                <h3 className="text-sm font-bold text-white">Grad-CAM</h3>
                <img
                  src={`data:image/png;base64,${analysis.gradcam_image}`}
                  alt="Grad-CAM"
                  className="w-full rounded-lg border border-slate-700"
                />
              </section>
            )}

            {/* CLAHE */}
            {analysis.clahe_image && (
              <section className="space-y-2">
                <h3 className="text-sm font-bold text-white">CLAHE Enhanced</h3>
                <img
                  src={`data:image/png;base64,${analysis.clahe_image}`}
                  alt="CLAHE"
                  className="w-full rounded-lg border border-slate-700"
                />
              </section>
            )}

            <div className="flex items-center gap-1.5 text-[10px] text-emerald-600">
              <CheckCircle2 className="h-3 w-3" />
              Analysis completed
            </div>

            {reportText && (
              <section className="space-y-2">
                <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5 text-blue-400" />
                  Clinical Report
                </h3>
                <div className="rounded-lg bg-[#121936] border border-slate-700 p-3">
                  <pre className="text-xs text-slate-300 whitespace-pre-wrap font-sans leading-relaxed">
                    {reportText}
                  </pre>
                </div>
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
              disabled={loading || generatingReport}
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition"
            >
              {loading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              {loading ? "Running…" : hasAnalysis ? "Run Analysis Again" : "Run AI Analysis"}
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
