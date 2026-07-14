import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  BadgeCheck,
  Calendar,
  FileText,
  Loader2,
  User,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { fetchMedicalReports, getExam } from "@/lib/exam-api";
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

function CompteRenduPage() {
  const { id } = Route.useParams();
  const [exam, setExam] = useState<Exam | null>(null);
  const [report, setReport] = useState<MedicalReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
        setReport(reports[0] ?? null);
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
          <div className="mx-auto max-w-5xl overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-200 px-6 py-5">
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

              <div className="mt-5 grid gap-3 text-sm text-slate-600 sm:grid-cols-3">
                <InfoItem icon={User} label="ID patient" value={exam?.patientId || "—"} />
                <InfoItem icon={Calendar} label="Date examen" value={exam?.date || "—"} />
                <InfoItem
                  icon={BadgeCheck}
                  label="Signature"
                  value={report?.signed_by_name || report?.validated_by_name || "Non renseignée"}
                />
              </div>
              <div className="mt-2 text-xs text-slate-500">
                Dernière mise à jour : {formatDateTime(report?.signed_at || report?.updated_at)}
              </div>
            </div>

            <article className="prose prose-slate max-w-none whitespace-pre-wrap px-6 py-6 text-sm leading-7 text-slate-800">
              {content}
            </article>
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
