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
      <circle
        cx="5"
        cy="5"
        r="2.5"
        fill="#ff6b6b"
        fillOpacity="0.45"
        stroke="#ff6b6b"
        strokeWidth="0.6"
      />
      <circle
        cx="10"
        cy="4"
        r="1.5"
        fill="#ffd93d"
        fillOpacity="0.5"
        stroke="#ffd93d"
        strokeWidth="0.5"
      />
      <circle
        cx="8"
        cy="9"
        r="1.2"
        fill="#a855f7"
        fillOpacity="0.6"
        stroke="#a855f7"
        strokeWidth="0.5"
      />
      <circle
        cx="4"
        cy="10"
        r="1"
        fill="#ff6b6b"
        fillOpacity="0.5"
        stroke="#ff6b6b"
        strokeWidth="0.4"
      />
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
        { label: "Lesion — Hemorrhage", color: "#ff6b6b" },
        { label: "Lesion — Exudate", color: "#ffd93d" },
        { label: "Lesion — Microaneurysm", color: "#a855f7" },
      ];
      legends.forEach((l, i) => {
        ctx.fillStyle = l.color;
        ctx.fillRect(20, 90 + i * 20, 12, 12);
        ctx.fillStyle = "#e2e8f0";
        ctx.font = "11px system-ui";
        ctx.fillText(l.label, 38, 100 + i * 20);
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
        if (exam && exam.status === "En attente" && exam.assignedTo) {
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
            {exam.qualityCategory && exam.qualityScore != null && (
              <span
                className={`inline-flex rounded px-2 py-0.5 text-[11px] font-bold ring-1 ${
                  exam.qualityCategory === "good"
                    ? "bg-emerald-900/60 text-emerald-300 ring-emerald-700"
                    : exam.qualityCategory === "acceptable"
                      ? "bg-amber-900/60 text-amber-300 ring-amber-700"
                      : "bg-red-900/60 text-red-300 ring-red-700"
                }`}
              >
                Qualité {exam.qualityCategory === "good" ? "bonne" : exam.qualityCategory === "acceptable" ? "acceptable" : "mauvaise"}
                {" · "}{exam.qualityScore.toFixed(1)}/100
              </span>
            )}
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
                      setActiveSegSeries(activeSegSeries === row.segType ? null : row.segType)
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
                    <td className="px-4 py-3 text-slate-400 font-mono text-xs">{row.series}</td>
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
                              activeSegSeries === row.segType ? null : row.segType!,
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
                {showViewer && hasStudy ? "OHIF Viewer — DICOM" : `${exam.type} — Rétinographie`}
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
                    {/* Vessel overlay — thin cyan lines with realistic branching */}
                    {(activeSegSeries === "vessel" || activeSegSeries === "all") && (
                      <svg
                        className="absolute inset-0 w-full h-full"
                        viewBox="0 0 420 420"
                        style={{ opacity: 0.8 }}
                      >
                        {/* Superior temporal arcade */}
                        <path
                          d="M170 205 Q200 175 250 145 Q290 120 330 95"
                          stroke="#00bcd4"
                          strokeWidth="1.5"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M250 145 Q270 130 280 110"
                          stroke="#00bcd4"
                          strokeWidth="0.9"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M250 145 Q260 140 275 155"
                          stroke="#00bcd4"
                          strokeWidth="0.8"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M290 120 Q310 110 340 115"
                          stroke="#00bcd4"
                          strokeWidth="1"
                          fill="none"
                          strokeLinecap="round"
                        />
                        {/* Superior nasal arcade */}
                        <path
                          d="M170 205 Q145 180 120 155 Q90 130 65 110"
                          stroke="#00bcd4"
                          strokeWidth="1.5"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M120 155 Q105 140 85 145"
                          stroke="#00bcd4"
                          strokeWidth="0.8"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M90 130 Q75 115 50 120"
                          stroke="#00bcd4"
                          strokeWidth="0.9"
                          fill="none"
                          strokeLinecap="round"
                        />
                        {/* Inferior temporal arcade */}
                        <path
                          d="M170 205 Q205 235 255 265 Q300 290 335 320"
                          stroke="#00bcd4"
                          strokeWidth="1.5"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M255 265 Q275 280 270 305"
                          stroke="#00bcd4"
                          strokeWidth="0.8"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M300 290 Q320 305 350 295"
                          stroke="#00bcd4"
                          strokeWidth="0.9"
                          fill="none"
                          strokeLinecap="round"
                        />
                        {/* Inferior nasal arcade */}
                        <path
                          d="M170 205 Q140 230 110 260 Q80 290 55 310"
                          stroke="#00bcd4"
                          strokeWidth="1.4"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M110 260 Q95 275 75 270"
                          stroke="#00bcd4"
                          strokeWidth="0.8"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M80 290 Q65 305 45 295"
                          stroke="#00bcd4"
                          strokeWidth="0.8"
                          fill="none"
                          strokeLinecap="round"
                        />
                        {/* Small macular branches */}
                        <path
                          d="M170 205 Q195 195 220 195 Q245 195 260 205"
                          stroke="#00bcd4"
                          strokeWidth="0.7"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M220 195 Q225 180 235 170"
                          stroke="#00bcd4"
                          strokeWidth="0.6"
                          fill="none"
                          strokeLinecap="round"
                        />
                        <path
                          d="M170 205 Q180 215 195 225"
                          stroke="#00bcd4"
                          strokeWidth="0.6"
                          fill="none"
                          strokeLinecap="round"
                        />
                      </svg>
                    )}
                    {/* Optic disc segmentation overlay — green contour with transparent mask */}
                    {(activeSegSeries === "optic-disc" || activeSegSeries === "all") && (
                      <svg
                        className="absolute inset-0 w-full h-full"
                        viewBox="0 0 420 420"
                        style={{ opacity: 0.9 }}
                      >
                        {/* Outer glow */}
                        <circle
                          cx="168"
                          cy="207"
                          r="42"
                          stroke="none"
                          fill="rgba(76,175,80,0.06)"
                        />
                        {/* Disc contour */}
                        <circle
                          cx="168"
                          cy="207"
                          r="38"
                          stroke="#4caf50"
                          strokeWidth="2.5"
                          fill="rgba(76,175,80,0.12)"
                        />
                        {/* Disc inner highlight */}
                        <circle
                          cx="168"
                          cy="207"
                          r="38"
                          stroke="none"
                          fill="rgba(76,175,80,0.04)"
                        />
                        {/* Cup contour */}
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
                    {/* Lesion segmentation overlay — red/yellow/purple pixel-level masks */}
                    {(activeSegSeries === "lesion" || activeSegSeries === "all") && (
                      <svg
                        className="absolute inset-0 w-full h-full"
                        viewBox="0 0 420 420"
                        style={{ opacity: 0.8 }}
                      >
                        {/* — Hemorrhages (red, irregular blobs) — */}
                        <path
                          d="M285 185 Q292 178 298 186 Q305 195 296 198 Q288 200 283 192 Z"
                          fill="rgba(255,70,70,0.5)"
                          stroke="#ff4646"
                          strokeWidth="1"
                        />
                        <path
                          d="M275 192 Q280 186 288 190 Q295 195 290 201 Q283 206 276 200 Z"
                          fill="rgba(255,70,70,0.4)"
                          stroke="#ff4646"
                          strokeWidth="0.8"
                        />
                        <path
                          d="M230 275 Q236 268 244 273 Q250 280 242 285 Q234 288 228 282 Z"
                          fill="rgba(255,70,70,0.55)"
                          stroke="#ff4646"
                          strokeWidth="1"
                        />
                        <path
                          d="M225 282 Q230 276 238 280 Q243 286 236 290 Q229 292 224 287 Z"
                          fill="rgba(255,70,70,0.35)"
                          stroke="#ff4646"
                          strokeWidth="0.8"
                        />
                        <path
                          d="M310 245 Q318 238 325 246 Q330 254 322 258 Q314 260 308 253 Z"
                          fill="rgba(255,70,70,0.45)"
                          stroke="#ff4646"
                          strokeWidth="0.8"
                        />

                        {/* — Exudates (yellow, clustered irregular patches) — */}
                        <path
                          d="M140 130 Q146 122 153 128 Q158 135 152 140 Q145 143 139 137 Z"
                          fill="rgba(255,217,61,0.55)"
                          stroke="#ffd93d"
                          strokeWidth="0.8"
                        />
                        <path
                          d="M148 122 Q154 116 161 120 Q166 127 159 132 Q152 135 147 129 Z"
                          fill="rgba(255,217,61,0.45)"
                          stroke="#ffd93d"
                          strokeWidth="0.7"
                        />
                        <path
                          d="M135 138 Q140 132 147 136 Q151 142 145 146 Q139 148 134 143 Z"
                          fill="rgba(255,217,61,0.4)"
                          stroke="#ffd93d"
                          strokeWidth="0.7"
                        />
                        <path
                          d="M155 115 Q160 108 168 112 Q173 119 166 124 Q159 127 154 121 Z"
                          fill="rgba(255,217,61,0.5)"
                          stroke="#ffd93d"
                          strokeWidth="0.8"
                        />
                        <path
                          d="M300 170 Q306 163 313 167 Q318 174 311 179 Q304 181 299 176 Z"
                          fill="rgba(255,217,61,0.5)"
                          stroke="#ffd93d"
                          strokeWidth="0.8"
                        />
                        <path
                          d="M308 164 Q314 158 320 162 Q325 169 318 173 Q312 175 307 170 Z"
                          fill="rgba(255,217,61,0.4)"
                          stroke="#ffd93d"
                          strokeWidth="0.7"
                        />
                        <path
                          d="M295 178 Q300 172 306 176 Q310 182 304 185 Q298 187 294 182 Z"
                          fill="rgba(255,217,61,0.35)"
                          stroke="#ffd93d"
                          strokeWidth="0.7"
                        />

                        {/* — Microaneurysms (purple, tiny pinpoint dots) — */}
                        <circle
                          cx="260"
                          cy="150"
                          r="2.5"
                          fill="rgba(168,85,247,0.7)"
                          stroke="#a855f7"
                          strokeWidth="0.6"
                        />
                        <circle
                          cx="268"
                          cy="155"
                          r="2"
                          fill="rgba(168,85,247,0.65)"
                          stroke="#a855f7"
                          strokeWidth="0.6"
                        />
                        <circle
                          cx="255"
                          cy="158"
                          r="1.8"
                          fill="rgba(168,85,247,0.6)"
                          stroke="#a855f7"
                          strokeWidth="0.5"
                        />
                        <circle
                          cx="265"
                          cy="145"
                          r="2.2"
                          fill="rgba(168,85,247,0.7)"
                          stroke="#a855f7"
                          strokeWidth="0.6"
                        />
                        <circle
                          cx="190"
                          cy="260"
                          r="2"
                          fill="rgba(168,85,247,0.65)"
                          stroke="#a855f7"
                          strokeWidth="0.6"
                        />
                        <circle
                          cx="196"
                          cy="265"
                          r="1.5"
                          fill="rgba(168,85,247,0.55)"
                          stroke="#a855f7"
                          strokeWidth="0.5"
                        />
                        <circle
                          cx="185"
                          cy="268"
                          r="1.8"
                          fill="rgba(168,85,247,0.6)"
                          stroke="#a855f7"
                          strokeWidth="0.5"
                        />
                        <circle
                          cx="340"
                          cy="200"
                          r="2"
                          fill="rgba(168,85,247,0.65)"
                          stroke="#a855f7"
                          strokeWidth="0.6"
                        />
                        <circle
                          cx="348"
                          cy="205"
                          r="1.5"
                          fill="rgba(168,85,247,0.55)"
                          stroke="#a855f7"
                          strokeWidth="0.5"
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
                    {(activeSegSeries === "optic-disc" || activeSegSeries === "all") && (
                      <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded-full border border-green-400 bg-green-400/20" />
                        <span>Disque optique</span>
                        <div className="w-3 h-3 rounded-full border border-red-400 bg-red-400/15 ml-1" />
                        <span>Cup</span>
                      </div>
                    )}
                    {(activeSegSeries === "lesion" || activeSegSeries === "all") && (
                      <>
                        <div className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold mt-1 mb-0.5">
                          Lésions
                        </div>
                        <div className="flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full border border-red-400 bg-red-400/40" />
                          <span>Hémorragies</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full border border-yellow-400 bg-yellow-400/40" />
                          <span>Exsudats</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full border border-purple-400 bg-purple-400/40" />
                          <span>Microanévrismes</span>
                        </div>
                      </>
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
              <AIPanel
                studyInstanceUid={exam.studyInstanceUid}
                seriesInstanceUid={exam.studyInstanceUid}
                patientId={exam.patientName}
                patientAge={exam.patientAge}
              />
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
                      { label: "Hémorragies", type: "lesion", color: "#ff6b6b", count: 5 },
                      { label: "Exsudats", type: "lesion", color: "#ffd93d", count: 7 },
                      { label: "Microanévrismes", type: "lesion", color: "#a855f7", count: 9 },
                      { label: "Vaisseaux", type: "vessel", color: "#00bcd4", count: 1 },
                      { label: "Disque optique", type: "optic-disc", color: "#4caf50", count: 1 },
                    ].map((seg) => (
                      <button
                        key={seg.type}
                        onClick={() =>
                          setActiveSegSeries(activeSegSeries === seg.type ? null : seg.type)
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
                    onClick={() => setActiveSegSeries(activeSegSeries === "all" ? null : "all")}
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
