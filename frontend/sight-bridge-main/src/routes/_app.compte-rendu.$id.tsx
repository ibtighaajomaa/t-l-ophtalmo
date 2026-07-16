import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  BadgeCheck,
  Bold,
  Calendar,
  FileText,
  Heading2,
  Italic,
  List,
  ListOrdered,
  Loader2,
  Save,
  Underline,
  User,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { fetchMedicalReports, getExam, updateMedicalReport } from "@/lib/exam-api";
import type { Exam } from "@/lib/mock-worklist";
import type { MedicalReport } from "@/lib/exam-api";

export const Route = createFileRoute("/_app/compte-rendu/$id")({
  component: CompteRenduPage,
});

function formatDateTime(value?: string | null) {
  if (!value) return "Non renseigné";
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function reportContent(report: MedicalReport | null) {
  if (!report) return "";
  return report.final_content || report.doctor_content || report.ai_content || "";
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function normalizeReportHtml(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (/<(h[1-6]|p|ul|ol|li|br|strong|b|em|i|u|div|section)\b/i.test(trimmed)) {
    return trimmed.replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, "");
  }
  return trimmed
    .split(/\n{2,}/)
    .map((paragraph) => `<p>${escapeHtml(paragraph).replace(/\n/g, "<br>")}</p>`)
    .join("");
}

function CompteRenduPage() {
  const { id } = Route.useParams();
  const [exam, setExam] = useState<Exam | null>(null);
  const [report, setReport] = useState<MedicalReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editorHtml, setEditorHtml] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadCompteRendu() {
      setLoading(true);
      setError(null);
      try {
        const loadedExam = await getExam(id);
        if (cancelled) return;
        setExam(loadedExam);

        if (loadedExam.status !== "Interprété") {
          setReport(null);
          return;
        }

        const reports = await fetchMedicalReports(loadedExam.id.replace(/^EX-/, ""));
        if (cancelled) return;
        const loadedReport = reports[0] ?? null;
        setReport(loadedReport);
        setEditorHtml(normalizeReportHtml(reportContent(loadedReport)));
      } catch (err) {
        if (!cancelled) {
          console.error("[CompteRendu] Failed to load report:", err);
          setError("Impossible de charger le compte rendu.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadCompteRendu();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const content = useMemo(() => reportContent(report), [report]);
  const isAvailable = exam?.status === "Interprété" && Boolean(content.trim());

  const applyFormat = (command: string, value?: string) => {
    editorRef.current?.focus();
    document.execCommand(command, false, value);
    setEditorHtml(editorRef.current?.innerHTML ?? "");
  };

  const handleSave = async () => {
    if (!report) return;
    const html = editorRef.current?.innerHTML ?? editorHtml;
    setEditorHtml(html);
    setSaving(true);
    setSaveMessage(null);
    try {
      const updated = await updateMedicalReport(report.id, html, {
        studyInstanceUid: exam?.studyInstanceUid,
      });
      window.dispatchEvent(
        new CustomEvent("teleoph.medical-report-updated", {
          detail: { examinationId: updated.examination_id, reportId: updated.id },
        }),
      );
      localStorage.setItem("teleoph.medical-report-updated", String(Date.now()));
      setReport(updated);
      const normalized = normalizeReportHtml(reportContent(updated) || html);
      setEditorHtml(normalized);
      if (editorRef.current) editorRef.current.innerHTML = normalized;
      setSaveMessage("Compte rendu enregistré.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Échec de l'enregistrement.";
      setSaveMessage(message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <>
        <Navbar title="Compte rendu" subtitle="Chargement du document" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      </>
    );
  }

  return (
    <>
      <Navbar
        title="Compte rendu"
        subtitle={exam ? `${exam.patientName} · ${exam.date}` : "Document médical"}
      />
      <div className="flex-1 p-6">
        <Link
          to="/worklist"
          className="mb-5 inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-blue-600"
        >
          <ArrowLeft className="h-4 w-4" /> Worklist
        </Link>

        {error ? (
          <UnavailableMessage message={error} />
        ) : !isAvailable ? (
          <UnavailableMessage message="Le compte rendu n'est pas disponible." />
        ) : (
          <div className="mx-auto max-w-6xl overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-200 bg-gradient-to-r from-white to-slate-50 px-6 py-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold text-blue-700">
                    <FileText className="h-4 w-4" />
                    Compte rendu d'interprétation
                  </div>
                  <h1 className="mt-2 text-2xl font-semibold text-slate-950">
                    {exam?.patientName}
                  </h1>
                </div>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-green-50 px-3 py-1 text-xs font-semibold text-green-700 ring-1 ring-green-200">
                  <BadgeCheck className="h-3.5 w-3.5" />
                  Interprété
                </span>
              </div>

              <div className="mt-5 grid gap-3 text-sm text-slate-600 sm:grid-cols-2">
                <InfoItem icon={User} label="ID patient" value={exam?.patientId || "—"} />
                <InfoItem icon={Calendar} label="Date examen" value={exam?.date || "—"} />
              </div>
              <div className="mt-2 text-xs text-slate-500">
                Dernière mise à jour : {formatDateTime(report?.signed_at || report?.updated_at)}
              </div>
            </div>

            <div className="border-b border-slate-200 bg-white px-6 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <EditorButton label="Titre" icon={Heading2} onClick={() => applyFormat("formatBlock", "h2")} />
                <EditorButton label="Gras" icon={Bold} onClick={() => applyFormat("bold")} />
                <EditorButton label="Italique" icon={Italic} onClick={() => applyFormat("italic")} />
                <EditorButton label="Souligné" icon={Underline} onClick={() => applyFormat("underline")} />
                <EditorButton
                  label="Liste"
                  icon={List}
                  onClick={() => applyFormat("insertUnorderedList")}
                />
                <EditorButton
                  label="Liste numérotée"
                  icon={ListOrdered}
                  onClick={() => applyFormat("insertOrderedList")}
                />
              </div>
            </div>

            <div className="bg-slate-50 px-6 py-6">
              <div
                ref={editorRef}
                contentEditable
                suppressContentEditableWarning
                className="min-h-[520px] rounded-xl border border-slate-200 bg-white px-7 py-6 text-[15px] leading-8 text-slate-900 shadow-inner outline-none transition focus:border-blue-300 focus:ring-4 focus:ring-blue-50 [&_h2]:mb-3 [&_h2]:mt-6 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-slate-950 [&_p]:mb-4 [&_ul]:mb-4 [&_ul]:list-disc [&_ul]:pl-6 [&_ol]:mb-4 [&_ol]:list-decimal [&_ol]:pl-6"
                dangerouslySetInnerHTML={{ __html: editorHtml }}
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white px-6 py-4">
              <div className="text-sm text-slate-500">
                {saveMessage ? saveMessage : "Modifiez le compte rendu puis enregistrez."}
              </div>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {saving ? "Enregistrement..." : "Enregistrer"}
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function InfoItem({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof User;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2">
      <Icon className="h-4 w-4 text-slate-400" />
      <div>
        <div className="text-[11px] font-medium uppercase text-slate-400">{label}</div>
        <div className="font-medium text-slate-700">{value}</div>
      </div>
    </div>
  );
}

function EditorButton({
  label,
  icon: Icon,
  onClick,
}: {
  label: string;
  icon: typeof Bold;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
      title={label}
      aria-label={label}
      className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}

function UnavailableMessage({ message }: { message: string }) {
  return (
    <div className="mx-auto max-w-2xl rounded-xl border border-amber-200 bg-amber-50 px-6 py-5 text-amber-800">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-5 w-5 flex-none" />
        <div>
          <h1 className="font-semibold">Compte rendu non disponible</h1>
          <p className="mt-1 text-sm">{message}</p>
        </div>
      </div>
    </div>
  );
}
