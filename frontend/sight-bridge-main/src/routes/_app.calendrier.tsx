import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState, useEffect } from "react";
import { toast } from "sonner";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { useAuth } from "@/lib/auth-context";
import { MOCK_PLANNING, PlanningSession } from "@/lib/mock-planning";
import { fetchExams } from "@/lib/exam-api";
import type { Exam } from "@/lib/mock-worklist";
import {
  ChevronLeft,
  ChevronRight,
  Search,
  Settings,
  HelpCircle,
  Menu,
  Plus,
  Calendar as CalendarIcon,
  ChevronDown,
  MapPin
} from "lucide-react";
import { Calendar } from "@/components/ui/calendar";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { fr } from "date-fns/locale";
import {
  format,
  addDays,
  startOfWeek,
  addWeeks,
  subWeeks,
  isSameDay,
  parse,
  isToday
} from "date-fns";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_app/calendrier")({
  component: () => (
    <ProtectedRoute roles={["Admin", "Chef", "Medecin", "Resident"]}>
      <CalendrierPage />
    </ProtectedRoute>
  ),
});

// Helper pour parser la date "Jeudi 08 janvier 2026"
function parseFrenchDate(dateStr: string): Date | null {
  try {
    return parse(dateStr.toLowerCase(), 'eeee dd MMMM yyyy', new Date(), { locale: fr });
  } catch (e) {
    return null;
  }
}

const HOURS = Array.from({ length: 16 }, (_, i) => i + 8); // 8 AM to 11 PM

function CalendrierPage() {
  const { user } = useAuth();

  // Date de référence pour correspondre aux mocks (Juin 2026)
  const defaultDate = new Date(2026, 5, 26);
  const [currentDate, setCurrentDate] = useState(defaultDate);
  const [exams, setExams] = useState<Exam[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [selectedSlot, setSelectedSlot] = useState<{ day: Date, hour: number } | null>(null);
  const [newSessionDoctor, setNewSessionDoctor] = useState<string>("");
  const [newSessionCount, setNewSessionCount] = useState<number>(1);
  const [newSessionStartHour, setNewSessionStartHour] = useState<number>(8);
  const [newSessionEndHour, setNewSessionEndHour] = useState<number>(10);
  const [editingSessionId, setEditingSessionId] = useState<number | null>(null);

  useEffect(() => {
    fetchExams({ page_size: 100 })
      .then((r) => setExams(r.exams))
      .catch(() => { });
  }, []);

  const normalize = (name: string) => name.toLowerCase().replace(/^(dr\.|pr|dr)\s+/i, '').trim();

  const parsedPlanning = useMemo(() => {
    return MOCK_PLANNING.map(session => {
      let parsed = parseFrenchDate(session.date);
      // Fallback si la date ne se parse pas bien
      if (isNaN(parsed?.getTime() || NaN)) {
        parsed = new Date();
      }
      return {
        ...session,
        parsedDate: parsed as Date
      };
    }).filter(s => s.parsedDate !== null);
  }, []);

  const [planning, setPlanning] = useState<any[]>([]);

  const fetchSessions = () => {
    fetch('/api/users/sessions/')
      .then(r => r.json())
      .then(data => {
        if (data.sessions) {
          setPlanning(data.sessions.map((s: any) => ({
            ...s,
            parsedDate: new Date(s.parsedDate)
          })));
        }
      })
      .catch(e => console.error(e));
  };

  useEffect(() => {
    fetchSessions();
  }, []);
  const [doctors, setDoctors] = useState<string[]>([]);
  const [doctorEmails, setDoctorEmails] = useState<Record<string, string>>({});

  useEffect(() => {
    const fetchDoctors = async () => {
      try {
        const res = await fetch('/api/users/paginated/?page=1&size=100');
        const data = await res.json();
        if (data.users) {
          const docs = new Set<string>();
          const emails: Record<string, string> = {};
          data.users.forEach((u: any) => {
            if ((u.role === "Medecin" || u.role === "Resident" || u.role === "Chef") && u.is_disponible) {
              const title = u.role === "Chef" ? "Pr" : "Dr";
              const fullName = `${title} ${u.firstName} ${u.lastName}`;
              docs.add(fullName);
              emails[fullName] = u.email;
            }
          });
          setDoctors(Array.from(docs).sort());
          setDoctorEmails(emails);
        }
      } catch (err) {
        console.error("Erreur de chargement des médecins", err);
      }
    };
    fetchDoctors();
  }, []);

  const [selectedDoctors, setSelectedDoctors] = useState<Set<string>>(new Set(doctors));

  useEffect(() => {
    if (user?.role === "Admin") {
      setSelectedDoctors(new Set(doctors));
    } else if (user?.firstName) {
      setSelectedDoctors(new Set([`Dr ${user.firstName} ${user.lastName}`]));
    } else {
      setSelectedDoctors(new Set(doctors));
    }
  }, [doctors, user]);

  const toggleDoctor = (doc: string) => {
    const next = new Set(selectedDoctors);
    if (next.has(doc)) next.delete(doc);
    else next.add(doc);
    setSelectedDoctors(next);
  };

  const filteredPlanning = useMemo(() => {
    return planning.filter(p => selectedDoctors.has(p.doctorName));
  }, [planning, selectedDoctors]);

  const weekStart = startOfWeek(currentDate, { weekStartsOn: 0 }); // Sunday as start

  const weekDays = useMemo(() => {
    return Array.from({ length: 7 }).map((_, i) => addDays(weekStart, i));
  }, [weekStart]);

  const nextWeek = () => setCurrentDate(addWeeks(currentDate, 1));
  const prevWeek = () => setCurrentDate(subWeeks(currentDate, 1));
  const goToday = () => setCurrentDate(new Date());

  const formatHour = (hour: number) => {
    if (hour === 12) return "12 PM";
    if (hour > 12) return `${hour - 12} PM`;
    return `${hour} AM`;
  };

  const getEventColor = (affiliation: string) => {
    if (affiliation.includes("Razi")) return "bg-gradient-to-br from-amber-50/90 to-orange-100/90 text-orange-950 border border-orange-200/80 border-l-[5px] border-l-orange-400 shadow-sm shadow-orange-500/5";
    if (affiliation.includes("libre pratique")) return "bg-gradient-to-br from-blue-50/90 to-indigo-100/90 text-indigo-950 border border-indigo-200/80 border-l-[5px] border-l-indigo-400 shadow-sm shadow-indigo-500/5";
    if (affiliation.includes("Mongi Slim")) return "bg-gradient-to-br from-purple-50/90 to-fuchsia-100/90 text-fuchsia-950 border border-fuchsia-200/80 border-l-[5px] border-l-fuchsia-400 shadow-sm shadow-fuchsia-500/5";
    return "bg-gradient-to-br from-slate-50/90 to-slate-100/90 text-slate-900 border border-slate-200/80 border-l-[5px] border-l-slate-400 shadow-sm shadow-slate-500/5";
  };

  return (
    <div className="flex h-screen flex-col bg-gradient-to-br from-slate-50 via-white to-slate-50/80 overflow-hidden text-slate-900 font-sans relative z-10">
      {/* HEADER */}
      <header className="flex h-16 flex-none items-center justify-between border-b border-slate-200/60 bg-white/70 backdrop-blur-xl px-4 py-2 relative z-50 shadow-[0_1px_3px_0_rgba(0,0,0,0.02)]">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => setSidebarOpen(!sidebarOpen)} className="text-slate-500 rounded-full h-10 w-10 hover:bg-slate-100/80 hover:text-slate-800 transition-all duration-200 active:scale-95">
            <Menu className="h-5 w-5" />
          </Button>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-indigo-600 text-white font-bold text-lg shadow-lg shadow-blue-600/20 ring-2 ring-white transform transition-transform hover:rotate-3 cursor-default">
              {format(new Date(), 'dd')}
            </div>
            <span className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-700 to-indigo-700 hidden sm:block tracking-tight drop-shadow-sm">Agenda</span>
          </div>
          <div className="ml-8 flex items-center gap-3">
            <Button variant="outline" onClick={goToday} className="rounded-full px-5 h-9 text-sm font-semibold border-slate-200 hover:bg-blue-50/80 hover:border-blue-200 hover:text-blue-700 text-slate-700 transition-all duration-200 shadow-sm active:scale-95">
              Aujourd'hui
            </Button>
            <div className="flex items-center gap-1 ml-2 bg-slate-100/50 rounded-full p-0.5 border border-slate-200/50">
              <Button variant="ghost" size="icon" onClick={prevWeek} className="h-8 w-8 rounded-full text-slate-600 hover:bg-white hover:shadow-sm transition-all duration-200 active:scale-95">
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" onClick={nextWeek} className="h-8 w-8 rounded-full text-slate-600 hover:bg-white hover:shadow-sm transition-all duration-200 active:scale-95">
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
            <h2 className="ml-4 text-xl font-semibold capitalize text-slate-800 tracking-tight w-48">
              {format(currentDate, "MMMM yyyy", { locale: fr })}
            </h2>
          </div>
        </div>

        <div className="flex items-center gap-2">





        </div>
      </header>

      {/* BODY */}
      <div className="flex flex-1 overflow-hidden bg-transparent">
        {/* SIDEBAR */}
        {sidebarOpen && (
          <aside className="w-[280px] flex-none border-r border-slate-200/60 bg-white/40 backdrop-blur-2xl flex flex-col overflow-y-auto hidden md:block relative z-20">
            <div className="px-5 py-5 border-b border-slate-100/60 flex flex-col gap-4">
              <input
                type="date"
                value={format(currentDate, 'yyyy-MM-dd')}
                onChange={(e) => {
                  if (e.target.value) {
                    setCurrentDate(parse(e.target.value, 'yyyy-MM-dd', new Date()));
                  }
                }}
                className="w-full h-10 px-3 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all text-slate-700 bg-white shadow-sm"
              />
              <Calendar
                mode="single"
                selected={currentDate}
                onSelect={(date) => date && setCurrentDate(date)}
                className="w-full rounded-2xl border-none p-0 [&_.rdp-day]:h-8 [&_.rdp-day]:w-8 [&_.rdp-caption]:h-8 [&_.rdp-day_button:hover]:bg-blue-50/80 [&_.rdp-day_button:hover]:text-blue-700 [&_.rdp-day.rdp-day_selected]:bg-blue-600 [&_.rdp-day.rdp-day_selected]:text-white [&_.rdp-day.rdp-day_selected]:shadow-md [&_.rdp-day.rdp-day_selected]:shadow-blue-600/30 font-medium"
                locale={fr}
              />
            </div>

            <div className="flex-1 px-5 py-6 space-y-8 overflow-y-auto custom-scrollbar">
              <div className="relative group">
                <Search className="absolute left-3.5 top-2.5 h-4 w-4 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
                <input
                  type="text"
                  placeholder="Rechercher des médecins..."
                  className="h-10 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-4 text-sm focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all shadow-sm placeholder:text-slate-400"
                />
              </div>
            </div>
          </aside>
        )}

        {/* MAIN CALENDAR GRID */}
        <main className="flex flex-1 flex-col overflow-hidden bg-transparent relative z-0">
          {/* Days Header */}
          <div className="flex flex-none border-b border-slate-200/60 bg-white/60 backdrop-blur-xl z-30 shadow-[0_1px_2px_0_rgba(0,0,0,0.01)]">
            <div className="w-[60px] flex-none text-[10px] font-semibold text-slate-400 flex items-end justify-center pb-3 border-r border-slate-200/60">
              GMT+01
            </div>
            <div className="flex flex-1">
              {weekDays.map((day) => {
                const isSelected = isSameDay(day, currentDate);
                const isActualToday = isSameDay(day, new Date());
                return (
                  <div
                    key={day.toString()}
                    onClick={() => setCurrentDate(day)}
                    className="flex-1 flex flex-col items-center py-3 border-r border-slate-200/60 last:border-r-0 min-w-[60px] group cursor-pointer hover:bg-slate-50/50 transition-colors"
                  >
                    <span className={cn("text-[11px] font-bold uppercase tracking-wider mb-1.5 transition-colors duration-200", isSelected ? "text-blue-600" : isActualToday ? "text-slate-800" : "text-slate-500 group-hover:text-slate-700")}>
                      {format(day, 'EEE', { locale: fr }).replace('.', '')}
                    </span>
                    <div className={cn(
                      "flex h-11 w-11 items-center justify-center rounded-full text-xl font-medium transition-all duration-300",
                      isSelected
                        ? "bg-blue-600 text-white shadow-lg shadow-blue-500/30 ring-2 ring-blue-600 ring-offset-2 ring-offset-white/50"
                        : isActualToday
                          ? "text-slate-900 bg-slate-200/60 hover:bg-slate-200"
                          : "text-slate-700 group-hover:bg-slate-100 group-hover:text-slate-900"
                    )}>
                      {format(day, 'd')}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Scrollable Hours Grid */}
          <div className="flex flex-1 overflow-y-auto relative bg-white/20 custom-scrollbar backdrop-blur-[2px]">
            {/* Time labels axis */}
            <div className="w-[60px] flex-none bg-white/60 backdrop-blur-md border-r border-slate-200/60 relative z-20 pt-4">
              {HOURS.map((hour) => (
                <div key={hour} className="h-20 relative">
                  <span className="absolute -top-2.5 right-3 text-[11px] text-slate-500 font-medium tracking-tight">
                    {formatHour(hour)}
                  </span>
                </div>
              ))}
            </div>

            {/* Grid Cells */}
            <div className="flex flex-1 relative pt-4">
              {/* Background horizontal lines */}
              <div className="absolute inset-0 pointer-events-none z-0 pt-4">
                {HOURS.map((hour) => (
                  <div key={`line-${hour}`} className="h-20 border-b border-slate-200/40 w-full" />
                ))}
              </div>

              {weekDays.map((day, dayIdx) => (
                <div key={dayIdx} className="flex-1 border-r border-slate-200/60 last:border-r-0 relative min-w-[60px] z-10 group/col">
                  {/* Empty cells for hover effect to invite creation */}
                  <div className="absolute inset-0 flex flex-col z-0 pointer-events-auto mt-4">
                    {HOURS.map((hour) => (
                      <div
                        key={`slot-${hour}`}
                        className="h-20 w-full hover:bg-blue-50/40 transition-colors duration-200 cursor-pointer border border-transparent hover:border-blue-100"
                        onClick={() => {
                          setEditingSessionId(null);
                          setSelectedSlot({ day, hour });
                          setNewSessionStartHour(hour);
                          setNewSessionEndHour(Math.min(22, hour + 2));
                          const currentUserTitle = user?.role === "Chef" ? "Pr" : "Dr";
                          const currentUserFullName = user ? `${currentUserTitle} ${user.firstName} ${user.lastName}` : "";
                          setNewSessionDoctor(user?.role !== "Admin" ? currentUserFullName : "");
                          setNewSessionCount(1);
                          setIsCreateDialogOpen(true);
                        }}
                      />
                    ))}
                  </div>

                  {/* Events for this day */}
                  {(() => {
                    const daySessions = filteredPlanning
                      .filter(p => isSameDay(p.parsedDate, day))
                      .map((session, i) => {
                        const startHour = session.startHour !== undefined ? session.startHour : (8 + (i * 1.5));
                        const endHour = session.endHour !== undefined ? session.endHour : (startHour + 1.5);
                        return { ...session, _start: startHour, _end: endHour };
                      })
                      .sort((a, b) => a._start - b._start);

                    const clusters: any[][] = [];
                    let currentCluster: any[] = [];
                    let clusterEnd = -1;

                    daySessions.forEach(session => {
                      if (session._start >= clusterEnd) {
                        if (currentCluster.length > 0) clusters.push(currentCluster);
                        currentCluster = [session];
                        clusterEnd = session._end;
                      } else {
                        currentCluster.push(session);
                        clusterEnd = Math.max(clusterEnd, session._end);
                      }
                    });
                    if (currentCluster.length > 0) clusters.push(currentCluster);

                    const renderedSessions: any[] = [];
                    clusters.forEach(cluster => {
                      cluster.forEach((session, idx) => {
                        renderedSessions.push({
                          ...session,
                          _overlapIndex: idx,
                          _overlapCount: cluster.length
                        });
                      });
                    });

                    return renderedSessions.map((session) => {
                      const duration = Math.max(0.5, session._end - session._start);
                      if (session._start > 22) return null;

                      const topPos = (session._start - 8) * 80;
                      const height = duration * 80;
                      // Use 85% of total width to always leave a 15% clickable area on the right
                      const widthPct = 85 / session._overlapCount;
                      const leftPct = (session._overlapIndex / session._overlapCount) * 85;

                      return (
                        <div
                          key={session.id}
                          className={cn(
                            "absolute rounded-xl p-1.5 sm:p-2 text-xs overflow-hidden flex flex-col transition-all duration-300 cursor-pointer z-20 hover:z-30 hover:-translate-y-0.5 hover:shadow-xl backdrop-blur-md ring-1 ring-white/60",
                            getEventColor(session.affiliation)
                          )}
                          style={{
                            top: `${topPos + 2}px`,
                            height: `${height - 4}px`,
                            left: `calc(${leftPct}% + 4px)`,
                            width: `calc(${widthPct}% - 8px)`
                          }}
                          onClick={(e) => {
                            e.stopPropagation();
                            const currentUserTitle = user?.role === "Chef" ? "Pr" : "Dr";
                            const currentUserFullName = user ? `${currentUserTitle} ${user.firstName} ${user.lastName}` : "";
                            if (user?.role !== "Admin" && session.doctorName !== currentUserFullName) return;
                            setEditingSessionId(session.id);
                            setSelectedSlot({ day: session.parsedDate, hour: session.startHour || 8 });
                            setNewSessionStartHour(session.startHour || 8);
                            setNewSessionEndHour(session.endHour || 10);
                            setNewSessionDoctor(session.doctorName);
                            setNewSessionCount(session.count || 1);
                            setIsCreateDialogOpen(true);
                          }}
                        >
                          <span className="font-semibold block leading-tight tracking-tight break-words">
                            {session.doctorName}
                          </span>
                        </div>
                      );
                    });
                  })()}


                </div>
              ))}
            </div>
          </div>
        </main>
      </div>

      {/* DIALOG CREATION SESSION */}
      <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
        <DialogContent className="sm:max-w-[425px] rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold text-slate-800">
              {editingSessionId ? "Modifier la session d'examen" : "Nouvelle session d'examen"}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-5 py-4">
            {selectedSlot && (
              <div className="text-sm text-slate-500 bg-slate-50 p-3 rounded-xl border border-slate-100 flex items-center gap-2">
                <CalendarIcon className="h-4 w-4 text-blue-500" />
                <span>
                  <span className="font-semibold text-slate-700 capitalize">{format(selectedSlot.day, 'eeee dd MMMM yyyy', { locale: fr })}</span>
                </span>
              </div>
            )}

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="startHour" className="text-right text-slate-600 font-medium">De</Label>
              <Select value={newSessionStartHour.toString()} onValueChange={(val) => setNewSessionStartHour(parseInt(val))}>
                <SelectTrigger id="startHour" className="col-span-3 rounded-xl border-slate-200 focus:ring-blue-500">
                  <SelectValue placeholder="Heure de début" />
                </SelectTrigger>
                <SelectContent className="rounded-xl">
                  {HOURS.map(h => (
                    <SelectItem key={h} value={h.toString()}>{formatHour(h)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="endHour" className="text-right text-slate-600 font-medium">À</Label>
              <Select value={newSessionEndHour.toString()} onValueChange={(val) => setNewSessionEndHour(parseInt(val))}>
                <SelectTrigger id="endHour" className="col-span-3 rounded-xl border-slate-200 focus:ring-blue-500">
                  <SelectValue placeholder="Heure de fin" />
                </SelectTrigger>
                <SelectContent className="rounded-xl">
                  {HOURS.filter(h => h > newSessionStartHour).map(h => (
                    <SelectItem key={h} value={h.toString()}>{formatHour(h)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="doctor" className="text-right text-slate-600 font-medium">Médecin</Label>
              <div className="col-span-3">
                <Select value={newSessionDoctor} onValueChange={setNewSessionDoctor} disabled={user?.role !== "Admin"}>
                  <SelectTrigger id="doctor" className="rounded-xl border-slate-200 focus:ring-blue-500 disabled:opacity-100 disabled:cursor-not-allowed">
                    <SelectValue placeholder="Sélectionner un médecin" />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl">
                    {doctors.map(doc => (
                      <SelectItem key={doc} value={doc}>{doc}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="count" className="text-right text-slate-600 font-medium">Nb. examens</Label>
              <Input
                id="count"
                type="number"
                min="0"
                max="100"
                className="col-span-3 rounded-xl border-slate-200 focus:ring-blue-500"
                value={newSessionCount}
                onChange={(e) => setNewSessionCount(Math.min(100, Math.max(0, parseInt(e.target.value) || 0)))}
              />
            </div>
          </div>
          <DialogFooter className="gap-2 sm:gap-0 mt-2 flex flex-row items-center w-full">
            {editingSessionId && (
              <Button 
                variant="destructive" 
                onClick={async () => {
                  try {
                    await fetch(`/api/users/delete-session/${editingSessionId}/`, { method: 'DELETE' });
                    setPlanning(prev => prev.filter(s => s.id !== editingSessionId));
                  } catch (e) {
                    console.error("Erreur suppression", e);
                  }
                  setIsCreateDialogOpen(false);
                  setEditingSessionId(null);
                }} 
                className="rounded-xl mr-auto"
              >
                Supprimer
              </Button>
            )}
            <div className="flex gap-2 ml-auto">
              <Button variant="outline" onClick={() => setIsCreateDialogOpen(false)} className="rounded-xl">Annuler</Button>
              <Button onClick={async () => {
                if (newSessionDoctor && newSessionCount > 0) {
                  const email = doctorEmails[newSessionDoctor];
                  const sessionDate = selectedSlot ? selectedSlot.day : new Date();
                  
                  if (editingSessionId) {
                    try {
                      const r = await fetch(`/api/users/update-session/${editingSessionId}/`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email, count: newSessionCount, startHour: newSessionStartHour, endHour: newSessionEndHour })
                      });
                      const data = await r.json();
                      if (data.message) {
                        toast.info(data.message);
                      }
                      if (data.session) {
                        const updated = { ...data.session, parsedDate: new Date(data.session.parsedDate) };
                        setPlanning(prev => prev.map(s => s.id === editingSessionId ? updated : s));
                      }
                    } catch (e) {
                      console.error("Erreur update", e);
                    }
                  } else {
                    if (email) {
                      try {
                        const isoDate = new Date(sessionDate.getTime() - sessionDate.getTimezoneOffset() * 60000).toISOString().split('T')[0];
                        const r = await fetch('/api/users/assign-session/', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ email, count: newSessionCount, startHour: newSessionStartHour, endHour: newSessionEndHour, date: isoDate })
                        });
                        const data = await r.json();
                        if (data.message) {
                          toast.info(data.message);
                        }
                        if (data.session) {
                          const newS = { ...data.session, parsedDate: new Date(data.session.parsedDate) };
                          setPlanning(prev => [...prev, newS]);
                        } else if (data.error) {
                          toast.error(`Erreur : ${data.error}`);
                        }
                      } catch (e) {
                        console.error("Erreur assignation", e);
                        toast.error("Erreur réseau ou serveur lors de l'assignation.");
                      }
                    }
                  }
                }
                setIsCreateDialogOpen(false);
                setNewSessionDoctor("");
                setNewSessionCount(1);
                setEditingSessionId(null);
              }} className="rounded-xl bg-blue-600 hover:bg-blue-700 text-white shadow-md shadow-blue-500/20 transition-all">
                {editingSessionId ? "Enregistrer" : "Assigner"}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
