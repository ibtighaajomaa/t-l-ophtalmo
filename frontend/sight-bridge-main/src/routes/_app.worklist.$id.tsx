import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { ArrowLeft, Calendar, User, FileText, AlertCircle, MonitorPlay, Image, Loader2 } from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { AIPanel } from "@/components/AIPanel";
import { getExam } from "@/lib/exam-api";
import type { Exam } from "@/lib/mock-worklist";

export const Route = createFileRoute("/_app/worklist/$id")({
  component: ExamDetail,
});

function ExamDetail() {
  const { id } = Route.useParams();
  const [exam, setExam] = useState<Exam | null>(null);
  const [loading, setLoading] = useState(true);
  const [showViewer, setShowViewer] = useState(false);

  useEffect(() => {
    setLoading(true);
    getExam(id)
      .then(setExam)
      .catch(() => setExam(null))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <>
        <Navbar title="Chargement…" />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      </>
    );
  }

  if (!exam) {
    return (
      <>
        <Navbar title="Examen introuvable" />
        <div className="p-6">
          <Link to="/worklist" className="text-sm text-blue-600 hover:underline">
            ← Retour à la worklist
          </Link>
        </div>
      </>
    );
  }

  const hasStudy = !!exam.studyInstanceUid;

  return (
    <>
      <Navbar title={`Examen ${exam.id}`} subtitle={`${exam.type} · ${exam.date}`} />
      <div className="flex-1 p-6 space-y-6">
        <Link
          to="/worklist"
          className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-blue-600"
        >
          <ArrowLeft className="h-4 w-4" /> Worklist
        </Link>

        <div className="grid lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 rounded-xl border border-slate-200 bg-slate-900 overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2 text-xs text-slate-300">
              <span className="font-mono">
                {showViewer && hasStudy ? "OHIF Viewer — DICOM" : `${exam.type} — Œil droit (OD)`}
              </span>
              {hasStudy && (
                <button
                  onClick={() => setShowViewer((v) => !v)}
                  className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 transition"
                >
                  {showViewer ? (
                    <>
                      <Image className="h-3 w-3" /> Vue simulée
                    </>
                  ) : (
                    <>
                      <MonitorPlay className="h-3 w-3" /> Ouvrir OHIF Viewer
                    </>
                  )}
                </button>
              )}
            </div>

            {showViewer && hasStudy ? (
              <div className="relative" style={{ height: "600px" }}>
                <iframe
                  src={`/ohif/viewer?StudyInstanceUIDs=${exam.studyInstanceUid}`}
                  width="100%"
                  height="100%"
                  style={{ border: "none" }}
                  title="OHIF Viewer"
                  allowFullScreen
                />
              </div>
            ) : (
              <div className="aspect-square relative flex items-center justify-center bg-gradient-radial from-amber-900 via-slate-900 to-black">
                <div
                  className="absolute inset-8 rounded-full"
                  style={{
                    background:
                      "radial-gradient(circle at 50% 50%, #b8651b 0%, #6e3a0e 40%, #2a1505 70%, transparent 90%)",
                  }}
                />
                <div
                  className="absolute h-24 w-24 rounded-full"
                  style={{
                    left: "38%",
                    top: "42%",
                    background:
                      "radial-gradient(circle, #ffe0b3 0%, #f0a040 40%, transparent 80%)",
                    filter: "blur(2px)",
                  }}
                />
                <div className="absolute h-3 w-3 rounded-full bg-red-500 ring-4 ring-red-500/30 animate-pulse"
                  style={{ left: "62%", top: "55%" }}
                />
                <div className="relative text-center text-xs text-slate-400 backdrop-blur-sm bg-black/30 px-3 py-1.5 rounded">
                  {hasStudy
                    ? "Cliquez « Ouvrir OHIF Viewer » pour afficher les images DICOM"
                    : "Vue simulée — Rétinographie / OCT"}
                </div>
              </div>
            )}
          </div>

          <div className="space-y-4">
            {showViewer && hasStudy ? (
              <AIPanel />
            ) : (
              <>
                <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                  <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                    <User className="h-4 w-4 text-blue-600" /> Patient
                  </h3>
                  <div className="mt-3 space-y-2 text-sm">
                    <InfoRow label="Nom" value={exam.patientName} />
                    <InfoRow label="Âge" value={`${exam.patientAge} ans`} />
                    <InfoRow label="ID Examen" value={exam.id} mono />
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                  <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                    <FileText className="h-4 w-4 text-blue-600" /> Examen
                  </h3>
                  <div className="mt-3 space-y-2 text-sm">
                    <InfoRow label="Type" value={exam.type} />
                    <InfoRow
                      label="Date"
                      value={
                        <span className="inline-flex items-center gap-1">
                          <Calendar className="h-3 w-3" /> {exam.date}
                        </span>
                      }
                    />
                    <InfoRow label="Statut" value={exam.status} />
                    <InfoRow label="Assigné à" value={exam.assignedTo ?? "Non assigné"} />
                    <InfoRow
                      label="Priorité"
                      value={
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            exam.priority === "Urgent"
                              ? "bg-red-50 text-red-700"
                              : "bg-slate-100 text-slate-600"
                          }`}
                        >
                          {exam.priority}
                        </span>
                      }
                    />
                  </div>
                </div>

                {hasStudy && (
                  <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                    <div className="flex items-start gap-2 text-sm text-blue-900">
                      <MonitorPlay className="h-4 w-4 mt-0.5" />
                      <div>
                        <div className="font-medium">DICOM disponible</div>
                        <p className="mt-1 font-mono text-xs text-blue-700 break-all">
                          {exam.studyInstanceUid}
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {exam.notes && (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                    <div className="flex items-start gap-2 text-sm text-amber-900">
                      <AlertCircle className="h-4 w-4 mt-0.5" />
                      <div>
                        <div className="font-medium">Note clinique</div>
                        <p className="mt-1">{exam.notes}</p>
                      </div>
                    </div>
                  </div>
                )}

                <button className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 transition">
                  Rédiger l'interprétation
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function InfoRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-slate-900 ${mono ? "font-mono text-xs" : ""}`}>{value}</span>
    </div>
  );
}
