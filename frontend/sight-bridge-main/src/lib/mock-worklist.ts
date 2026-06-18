/** Mock data — Worklist d'examens ophtalmologiques */
export type ExamStatus = "En attente" | "En cours" | "Interprété";
export type ExamPriority = "Urgent" | "Normal";
export type ExamType = "Rétinographie" | "OCT" | "Champ visuel" | "Angiographie";

export interface Exam {
  id: string;
  patientName: string;
  patientAge: number;
  type: ExamType;
  date: string;
  priority: ExamPriority;
  status: ExamStatus;
  assignedTo: string | null;
  notes?: string;
  imageUrl?: string;
  region: string;
  modalityIp: string;
  doctorId?: string;
  createdByUserId?: string;
  studyInstanceUid?: string;
}

export const MOCK_EXAMS: Exam[] = [
  {
    id: "EX-1042",
    patientName: "Amina Cherif",
    patientAge: 64,
    type: "OCT",
    date: "2026-06-12",
    priority: "Urgent",
    status: "En attente",
    assignedTo: null,
    notes: "Suspicion de DMLA exsudative — œil droit.",
    region: "Alger",
    modalityIp: "192.168.10.50",
    doctorId: "gg@gmail.com",
    createdByUserId: "u-chef",
    studyInstanceUid: "1.3.6.1.4.1.14519.5.2.1.99.1071.55651399101931177647030363790032",
  },
  {
    id: "EX-1041",
    patientName: "Mohamed Saidi",
    patientAge: 58,
    type: "Rétinographie",
    date: "2026-06-12",
    priority: "Normal",
    status: "En cours",
    assignedTo: "Dr. Leïla Hadj",
    region: "Oran",
    modalityIp: "192.168.20.12",
    doctorId: "gg@gmail.com",
    createdByUserId: "u-admin",
    studyInstanceUid: "2.25.269859997690759739055099378767846712697",
  },
  {
    id: "EX-1040",
    patientName: "Fatima Zerrouki",
    patientAge: 72,
    type: "Champ visuel",
    date: "2026-06-11",
    priority: "Normal",
    status: "Interprété",
    assignedTo: "Dr. Leïla Hadj",
    notes: "Glaucome stable.",
    region: "Constantine",
    modalityIp: "192.168.30.5",
    doctorId: "u-med",
    createdByUserId: "u-med",
  },
  {
    id: "EX-1039",
    patientName: "Sofiane Boudjema",
    patientAge: 45,
    type: "OCT",
    date: "2026-06-11",
    priority: "Urgent",
    status: "En attente",
    assignedTo: null,
    region: "Alger",
    modalityIp: "192.168.10.51",
    createdByUserId: "u-admin",
  },
  {
    id: "EX-1038",
    patientName: "Nour El Houda",
    patientAge: 33,
    type: "Angiographie",
    date: "2026-06-10",
    priority: "Normal",
    status: "Interprété",
    assignedTo: "Dr. Karim Benali",
    region: "Annaba",
    modalityIp: "192.168.40.22",
    doctorId: "u-chef",
    createdByUserId: "u-chef",
  },
  {
    id: "EX-1037",
    patientName: "Hocine Belkacem",
    patientAge: 67,
    type: "Rétinographie",
    date: "2026-06-10",
    priority: "Normal",
    status: "En cours",
    assignedTo: "Dr. Karim Benali",
    region: "Alger",
    modalityIp: "192.168.10.50",
    doctorId: "u-chef",
    createdByUserId: "u-chef",
  },
];
