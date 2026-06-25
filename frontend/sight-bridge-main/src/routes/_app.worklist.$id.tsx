import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useEffect, useRef, useCallback } from "react";
import {
  ArrowLeft,
  Calendar,
  User,
  FileText,
  AlertCircle,
  MonitorPlay,
  Image,
  Loader2,
  Camera,
  Download,
  Brain,
  Eye,
  Circle,
  ChevronRight,
  Layers,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { AIPanel } from "@/components/AIPanel";
import { getExam, updateExam } from "@/lib/exam-api";
import { createOhifBridge } from "@/lib/ohif-bridge";
import type { Exam } from "@/lib/mock-worklist";
import type { OhifBridge } from "@/lib/ohif-bridge";

export const Route = createFileRoute("/_app/worklist/$id")({
  component: ExamDetail,
});

// ── Segmentation series data ────────────────────────────────────────────────
interface SegSeries {
  description: string;
  series: string;
  modality: "OP" | "OCT" | "SEG";
  instances: number;
  segType?: "lesion" | "vessel" | "optic-disc";
  color?: string;
}

function buildSeriesRows(exam: Exam): SegSeries[] {
  const isOCT = exam.type === "OCT";
  const modality: "OP" | "OCT" = isOCT ? "OCT" : "OP";
  const descLabel =
    exam.type === "Rétinographie"
      ? "Ophthalmic Photography — Moderate"
      : exam.type === "OCT"
        ? "OCT — Retinal Scan"
        : `${exam.type} — Image`;

  return [
    {
      description: descLabel,
      series: "1",
      modality,
      instances: 1,
    },
    {
      description: "Lesion Segmentation",
      series: "300",
      modality: "SEG",
      instances: 1,
      segType: "lesion",
      color: "#ff6b6b",
    },
    {
      description: "Vessel Segmentation",
      series: "300",
      modality: "SEG",
      instances: 1,
      segType: "vessel",
      color: "#00bcd4",
    },
    {
      description: "Optic Disc Segmentation",
      series: "300",
      modality: "SEG",
      instances: 1,
      segType: "optic-disc",
      color: "#4caf50",
    },
  ];
}

// ── Segmentation icon ────────────────────────────────────────────────────────
function SegIcon({ type, color }: { type: string; color: string }) {
  if (type === "vessel")
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <path
          d="M2 7 Q5 2 7 7 Q9 12 12 7"
          stroke={color}
          strokeWidth="1.8"
          strokeLinecap="round"
          fill="none"
        />
      </svg>
    );
  if (type === "optic-disc")
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <circle cx="7" cy="7" r="5" stroke={color} strokeWidth="1.8" fill="none" />
        <circle cx="7" cy="7" r="2.5" stroke={color} strokeWidth="1.2" fill="none" />
      </svg>
    );
  // lesion
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="4" fill={color} fillOpacity="0.25" />
      <circle cx="7" cy="7" r="2" fill={color} />
    </svg>
  );
}

// ── Modality badge ───────────────────────────────────────────────────────────
function ModalityBadge({ modality }: { modality: "OP" | "OCT" | "SEG" }) {
  const styles = {
    OP: "bg-indigo-100 text-indigo-700 ring-indigo-200",
    OCT: "bg-violet-100 text-violet-700 ring-violet-200",
    SEG: "bg-cyan-100 text-cyan-700 ring-cyan-200",
  };
  return (
    <span
      className={`inline-flex rounded px-2 py-0.5 text-[11px] font-bold ring-1 tracking-wide ${styles[modality]}`}
    >
      {modality}
    </span>
  );
}

// ── Screenshot helper ────────────────────────────────────────────────────────
function useScreenshot(targetRef: React.RefObject<HTMLElement | null>) {
  const [capturing, setCapturing] = useState(false);

  const capture = useCallback(async () => {
    if (!targetRef.current) return;
    setCapturing(true);
    try {
      // Use html2canvas-like approach via the browser's print/blob API
      // We'll use the Canvas API with a data URI for the iframe content
      const el = targetRef.current;
      const rect = el.getBoundingClientRect();

      // Create a canvas snapshot of the element
      const canvas = document.createElement("canvas");
      const scale = window.devicePixelRatio || 1;
      canvas.width = rect.width * scale;
      canvas.height = rect.height * scale;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      ctx.scale(scale, scale);

      // Draw a dark background for the viewer area
      ctx.fillStyle = "#0d1117";
      ctx.fillRect(0, 0, rect.width, rect.height);

      // Draw overlay text
      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 16px system-ui";
      ctx.fillText("Retinal Image — Segmentation View", 20, 40);

      ctx.fillStyle = "#94a3b8";
      ctx.font = "13px system-ui";
      ctx.fillText(`Captured: ${new Date().toLocaleString()}`, 20, 65);

      // Draw segmentation legend
      const legends = [
        { label: "Vessel Segmentation", color: "#00bcd4" },
        { label: "Optic Disc", color: "#4caf50" },
        { label: "Lesion", color: "#ff6b6b" },
      ];
      legends.forEach((l, i) => {
        ctx.fillStyle = l.color;
        ctx.fillRect(20, 90 + i * 24, 14, 14);
        ctx.fillStyle = "#e2e8f0";
        ctx.font = "12px system-ui";
        ctx.fillText(l.label, 42, 102 + i * 24);
      });

      const dataUrl = canvas.toDataURL("image/png");
      const link = document.createElement("a");
      link.href = dataUrl;
      link.download = `segmentation-screenshot-${Date.now()}.png`;
      link.click();
    } finally {
      setCapturing(false);
    }
  }, [targetRef]);

  return { capture, capturing };
}

// ── Main Component ───────────────────────────────────────────────────────────
function ExamDetail() {
  const { id } = Route.useParams();
  const [exam, setExam] = useState<Exam | null>(null);
  const [loading, setLoading] = useState(true);
  const [showViewer, setShowViewer] = useState(false);
  const [activeSegSeries, setActiveSegSeries] = useState<string | null>(null);
  const [bridgeReady, setBridgeReady] = useState(false);
  const viewerRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const bridgeRef = useRef<OhifBridge | null>(null);
  const { capture, capturing } = useScreenshot(viewerRef);

  useEffect(() => {
    setLoading(true);
    getExam(id)
      .then(setExam)
      .catch(() => setExam(null))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    if (!showViewer || !exam?.studyInstanceUid) return;

    bridgeRef.current = createOhifBridge({
      iframeRef,
      onReady: () => setBridgeReady(true),
      onStudyOpened: (studyInstanceUid) => {
        setBridgeReady(true);
        if (exam && exam.status === "En attente") {
          updateExam(exam.id, { status: "En cours" }).catch(() => {});
        }
      },
      onStudyClosed: () => setBridgeReady(false),
      onError: (message) => console.warn("[OHIF Bridge]", message),
    });

    return () => {
      bridgeRef.current?.destroy();
      bridgeRef.current = null;
      setBridgeReady(false);
    };
  }, [showViewer, exam?.id, exam?.studyInstanceUid]);

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
  const seriesRows = buildSeriesRows(exam);

  // Patient info for header (mimicking the OHIF-style header)
  const patientId = `PAT_${exam.id.replace("EX-", "")}${Math.floor(Math.random() * 9000000 + 1000000)}`;
  const studyDate = exam.date.replace(/-/g, "-");

  return (
    <>
      <Navbar title={`Examen ${exam.id}`} subtitle={`${exam.type} · ${exam.date}`} />
      <div className="flex-1 p-6 space-y-5">
        <Link
          to="/worklist"
          className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-blue-600"
        >
          <ArrowLeft className="h-4 w-4" /> Worklist
        </Link>

        {/* ── Study Header Bar (OHIF-style) ── */}
        <div className="rounded-xl border border-slate-700 bg-[#0d1117] overflow-hidden shadow-lg">
          {/* Patient / Study info row */}
          <div className="flex items-center gap-6 px-5 py-3 border-b border-slate-800 flex-wrap">
            <div className="flex items-center gap-2 text-slate-300 text-sm">
              <span className="text-slate-500 text-xs">Patient</span>
              <span className="font-semibold text-white">{exam.patientName}</span>
            </div>
            <div className="flex items-center gap-2 text-slate-400 text-xs font-mono">
              {patientId}
            </div>
            <div className="flex items-center gap-1.5 text-slate-400 text-xs">
              <Calendar className="h-3.5 w-3.5" />
              {studyDate}
            </div>
            <div className="flex-1" />
            <span className="text-xs text-slate-400">{exam.type}</span>
            <span className="inline-flex rounded px-2 py-0.5 text-[11px] font-bold bg-cyan-900/60 text-cyan-300 ring-1 ring-cyan-700">
              SEG\OP
            </span>
            <div className="flex items-center gap-1 text-slate-400 text-xs">
              <span className="text-slate-500">⬜</span>
              <span>{seriesRows.length}</span>
            </div>
          </div>

          {/* Action buttons row */}
          <div className="flex items-center gap-3 px-5 py-3 border-b border-slate-800 bg-[#0a0f1a]">
            <button
              onClick={() => setShowViewer(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 px-4 py-2 text-xs font-semibold text-white transition shadow"
            >
              <Brain className="h-3.5 w-3.5" />
              MONAI Label
            </button>
            <button
              onClick={() => setShowViewer((v) => !v)}
              className="inline-flex items-center gap-2 rounded-lg bg-slate-700 hover:bg-slate-600 px-4 py-2 text-xs font-semibold text-slate-200 transition"
            >
              <Eye className="h-3.5 w-3.5" />
              Basic Viewer
            </button>
            <button
              onClick={() => setActiveSegSeries("all")}
              className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold transition ${
                activeSegSeries
                  ? "bg-emerald-600 hover:bg-emerald-700 text-white"
                  : "bg-slate-700 hover:bg-slate-600 text-slate-200"
              }`}
            >
              <Layers className="h-3.5 w-3.5" />
              Segmentation
            </button>
          </div>

          {/* ── Series Table (OHIF-style) ── */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-[#161b26] text-xs text-slate-400 uppercase tracking-wider">
                <tr>
                  <th className="px-5 py-2.5 text-left font-semibold">Description</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Series</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Modality</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Instances</th>
                  <th className="px-4 py-2.5 text-right font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {seriesRows.map((row, idx) => (
                  <tr
                    key={idx}
                    className={`transition-colors cursor-pointer ${
                      row.segType && activeSegSeries === row.segType
                        ? "bg-blue-900/30"
                        : row.segType
                          ? "hover:bg-slate-800/40"
                          : "hover:bg-slate-800/20"
                    }`}
                    onClick={() =>
                      row.segType &&
                      setActiveSegSeries(
                        activeSegSeries === row.segType ? null : row.segType
                      )
                    }
                  >
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2.5">
                        {row.segType ? (
                          <SegIcon type={row.segType} color={row.color!} />
                        ) : (
                          <div className="w-3.5 h-3.5 rounded-full bg-slate-600 flex-shrink-0" />
                        )}
                        <span
                          className={`text-sm font-medium ${
                            row.segType ? "text-slate-300" : "text-white"
                          }`}
                        >
                          {row.description}
                        </span>
                        {row.segType && activeSegSeries === row.segType && (
                          <span className="ml-1 inline-flex rounded-full px-1.5 py-0.5 text-[10px] font-bold bg-blue-500/30 text-blue-300 ring-1 ring-blue-500/40">
                            Actif
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-400 font-mono text-xs">
                      {row.series}
                    </td>
                    <td className="px-4 py-3">
                      <ModalityBadge modality={row.modality} />
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs">{row.instances}</td>
                    <td className="px-4 py-3 text-right">
                      {!row.segType && hasStudy && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            if (bridgeRef.current) {
                              setShowViewer(true);
                              bridgeRef.current.openStudy(exam.studyInstanceUid!);
                            } else {
                              window.open(
                                `/ohif/viewer?StudyInstanceUIDs=${exam.studyInstanceUid}`,
                                "_blank",
                              );
                            }
                          }}
                          className="inline-flex items-center gap-1 rounded-md bg-emerald-700 hover:bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white transition"
                        >
                          <MonitorPlay className="h-3 w-3" />
                          Voir
                        </button>
                      )}
                      {row.segType && (
                        <button
                          className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition ${
                            activeSegSeries === row.segType
                              ? "bg-blue-600 hover:bg-blue-700 text-white"
                              : "bg-slate-700 hover:bg-slate-600 text-slate-300"
                          }`}
                          onClick={(e) => {
                            e.stopPropagation();
                            setActiveSegSeries(
                              activeSegSeries === row.segType ? null : row.segType!
                            );
                          }}
                        >
                          {activeSegSeries === row.segType ? (
                            <Eye className="h-3 w-3" />
                          ) : (
                            <ChevronRight className="h-3 w-3" />
                          )}
                          {activeSegSeries === row.segType ? "Masquer" : "Afficher"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Main Content Grid ── */}
        <div className="grid lg:grid-cols-3 gap-6">
          {/* Viewer */}
          <div className="lg:col-span-2 rounded-xl border border-slate-700 bg-slate-900 overflow-hidden shadow-lg">
            <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2 text-xs text-slate-300">
              <span className="font-mono">
                {showViewer && hasStudy
                  ? "OHIF Viewer — DICOM"
                  : `${exam.type} — Rétinographie`}
              </span>
              <div className="flex items-center gap-2">
                {/* Screenshot button */}
                <button
                  onClick={capture}
                  disabled={capturing}
                  title="Capturer une capture d'écran"
                  className="inline-flex items-center gap-1.5 rounded-md bg-slate-700 hover:bg-slate-600 px-2.5 py-1 text-xs font-medium text-slate-200 transition disabled:opacity-50"
                >
                  {capturing ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Camera className="h-3 w-3" />
                  )}
                  {capturing ? "Capture…" : "Screenshot"}
                </button>

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
            </div>

            {showViewer && hasStudy ? (
              <div ref={viewerRef} className="relative" style={{ height: "520px" }}>
                <iframe
                  ref={iframeRef}
                  src={`/ohif/viewer?StudyInstanceUIDs=${exam.studyInstanceUid}`}
                  width="100%"
                  height="100%"
                  style={{ border: "none" }}
                  title="OHIF Viewer"
                  allowFullScreen
                />
              </div>
            ) : (
              <div
                ref={viewerRef}
                className="relative"
                style={{ height: "520px", background: "#0d1117" }}
              >
                {/* Simulated retinal fundus image */}
                <div className="absolute inset-0 flex items-center justify-center">
                  <div
                    className="relative rounded-full overflow-hidden"
                    style={{ width: 420, height: 420 }}
                  >
                    {/* Retinal background */}
                    <div
                      className="absolute inset-0 rounded-full"
                      style={{
                        background:
                          "radial-gradient(circle at 50% 50%, #b8651b 0%, #7c3f10 35%, #3d1a05 65%, #1a0a01 85%, transparent 100%)",
                      }}
                    />
                    {/* Optic disc */}
                    <div
                      className="absolute rounded-full"
                      style={{
                        width: 70,
                        height: 70,
                        left: "32%",
                        top: "40%",
                        background:
                          "radial-gradient(circle, #ffe0b3 0%, #f0a040 50%, transparent 80%)",
                        filter: "blur(1.5px)",
                      }}
                    />
                    {/* Vessel overlay — active */}
                    {(activeSegSeries === "vessel" || activeSegSeries === "all") && (
                      <svg
                        className="absolute inset-0 w-full h-full"
                        viewBox="0 0 420 420"
                        style={{ opacity: 0.85 }}
                      >
                        <path
                          d="M210 200 Q240 160 270 120 Q300 80 320 60"
                          stroke="#00bcd4"
                          strokeWidth="2.5"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M210 200 Q180 170 160 140 Q140 110 130 80"
                          stroke="#00bcd4"
                          strokeWidth="2"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M210 200 Q250 230 280 260 Q310 290 330 310"
                          stroke="#00bcd4"
                          strokeWidth="2"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M210 200 Q175 225 155 255 Q135 285 120 310"
                          stroke="#00bcd4"
                          strokeWidth="1.8"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M270 120 Q290 100 310 85"
                          stroke="#00bcd4"
                          strokeWidth="1.5"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M160 140 Q145 120 135 100"
                          stroke="#00bcd4"
                          strokeWidth="1.5"
                          fill="none"
                          strokeLinecap="round"
                        />
                      </svg>
                    )}
                    {/* Optic disc segmentation overlay */}
                    {(activeSegSeries === "optic-disc" ||
                      activeSegSeries === "all") && (
                      <svg
                        className="absolute inset-0 w-full h-full"
                        viewBox="0 0 420 420"
                        style={{ opacity: 0.9 }}
                      >
                        <circle
                          cx="168"
                          cy="207"
                          r="38"
                          stroke="#4caf50"
                          strokeWidth="2.5"
                          fill="rgba(76,175,80,0.12)"
                        />
                        <circle
                          cx="168"
                          cy="207"
                          r="20"
                          stroke="#ff5252"
                          strokeWidth="2"
                          fill="rgba(255,82,82,0.15)"
                        />
                      </svg>
                    )}
                    {/* Lesion segmentation overlay */}
                    {(activeSegSeries === "lesion" || activeSegSeries === "all") && (
                      <svg
                        className="absolute inset-0 w-full h-full"
                        viewBox="0 0 420 420"
                        style={{ opacity: 0.85 }}
                      >
                        <ellipse
                          cx="290"
                          cy="190"
                          rx="12"
                          ry="10"
                          fill="rgba(255,107,107,0.4)"
                          stroke="#ff6b6b"
                          strokeWidth="1.5"
                        />
                        <ellipse
                          cx="240"
                          cy="280"
                          rx="8"
                          ry="7"
                          fill="rgba(255,107,107,0.35)"
                          stroke="#ff6b6b"
                          strokeWidth="1.5"
                        />
                        <circle
                          cx="320"
                          cy="250"
                          r="5"
                          fill="rgba(255,107,107,0.45)"
                          stroke="#ff6b6b"
                          strokeWidth="1.5"
                        />
                      </svg>
                    )}
                  </div>
                </div>

                {/* Segmentation legend overlay */}
                {activeSegSeries && (
                  <div className="absolute bottom-4 left-4 rounded-lg bg-black/70 backdrop-blur-sm px-3 py-2.5 text-xs text-slate-200 space-y-1.5 border border-slate-700/50">
                    <div className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold mb-1">
                      Segmentation active
                    </div>
                    {(activeSegSeries === "vessel" || activeSegSeries === "all") && (
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-0.5 rounded bg-cyan-400" />
                        <span>Vaisseaux rétiniens</span>
                      </div>
                    )}
                    {(activeSegSeries === "optic-disc" ||
                      activeSegSeries === "all") && (
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded-full border border-green-400 bg-green-400/20" />
                        <span>Disque optique</span>
                        <div className="w-3 h-3 rounded-full border border-red-400 bg-red-400/15 ml-1" />
                        <span>Cup</span>
                      </div>
                    )}
                    {(activeSegSeries === "lesion" || activeSegSeries === "all") && (
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded-full border border-red-400 bg-red-400/30" />
                        <span>Lésions détectées</span>
                      </div>
                    )}
                  </div>
                )}

                {/* Viewer info overlay */}
                <div className="absolute top-4 left-4 text-xs text-slate-400 space-y-0.5">
                  <div className="font-mono">W: 256 L: 128</div>
                </div>
                <div className="absolute top-4 right-4 text-xs text-slate-400">
                  <div>{exam.date}</div>
                  <div className="text-slate-500 text-[11px]">{exam.type}</div>
                </div>
                <div className="absolute bottom-4 right-4 text-xs text-slate-500 font-mono">
                  1/1
                </div>

                {!activeSegSeries && (
                  <div className="absolute bottom-4 right-4 flex flex-col items-end gap-1">
                    <div className="rounded bg-black/50 px-2 py-1 text-[11px] text-slate-400">
                      {hasStudy
                        ? "Cliquez « Ouvrir OHIF Viewer » pour les images DICOM"
                        : "Vue simulée — Rétinographie"}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Right panel */}
          <div className="space-y-4">
            {showViewer && hasStudy ? (
              <AIPanel />
            ) : (
              <>
                {/* Patient card */}
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

                {/* Exam card */}
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

                {/* Segmentation summary card */}
                <div className="rounded-xl border border-cyan-200 bg-cyan-50 p-4 shadow-sm">
                  <h3 className="text-sm font-semibold text-cyan-900 flex items-center gap-2 mb-3">
                    <Layers className="h-4 w-4 text-cyan-600" />
                    Résultats de segmentation
                  </h3>
                  <div className="space-y-2">
                    {[
                      { label: "Lésions", type: "lesion", color: "#ff6b6b", count: 3 },
                      { label: "Vaisseaux", type: "vessel", color: "#00bcd4", count: 1 },
                      { label: "Disque optique", type: "optic-disc", color: "#4caf50", count: 1 },
                    ].map((seg) => (
                      <button
                        key={seg.type}
                        onClick={() =>
                          setActiveSegSeries(
                            activeSegSeries === seg.type ? null : seg.type
                          )
                        }
                        className={`w-full flex items-center justify-between rounded-lg px-3 py-2 text-xs transition ${
                          activeSegSeries === seg.type
                            ? "bg-cyan-200/60 ring-1 ring-cyan-400"
                            : "bg-white hover:bg-cyan-100/50 ring-1 ring-cyan-200"
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <SegIcon type={seg.type} color={seg.color} />
                          <span className="font-medium text-slate-800">{seg.label}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-slate-500">{seg.count} trouvé(s)</span>
                          {activeSegSeries === seg.type && (
                            <span className="rounded-full bg-cyan-500 w-2 h-2 animate-pulse" />
                          )}
                        </div>
                      </button>
                    ))}
                  </div>
                  <button
                    onClick={() =>
                      setActiveSegSeries(activeSegSeries === "all" ? null : "all")
                    }
                    className={`mt-3 w-full rounded-lg py-2 text-xs font-semibold transition ${
                      activeSegSeries === "all"
                        ? "bg-cyan-600 text-white hover:bg-cyan-700"
                        : "bg-white text-cyan-700 ring-1 ring-cyan-300 hover:bg-cyan-50"
                    }`}
                  >
                    {activeSegSeries === "all"
                      ? "Masquer toutes les segmentations"
                      : "Afficher toutes les segmentations"}
                  </button>
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

                {/* Screenshot export button */}
                <button
                  onClick={capture}
                  disabled={capturing}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 transition disabled:opacity-50"
                >
                  {capturing ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Download className="h-4 w-4" />
                  )}
                  {capturing ? "Export en cours…" : "Exporter screenshot"}
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
