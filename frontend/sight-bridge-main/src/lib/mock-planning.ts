export interface PlanningSession {
  id: number;
  date: string;
  doctorName: string;
  affiliation: string;
  hospital: string;
}

export const MOCK_PLANNING: PlanningSession[] = [
  { id: 1, date: "Jeudi 08 janvier 2026", doctorName: "Pr Asma Bouden", affiliation: "Hôpital Razi", hospital: "Hôpital régional Kébili" },
  { id: 2, date: "Jeudi 22 janvier 2026", doctorName: "Pr Soumeyya Halayem", affiliation: "Hôpital Razi", hospital: "Hôpital régional Kébili" },
  { id: 3, date: "Jeudi 05 février 2026", doctorName: "Pr Zeineb Abbes", affiliation: "Hôpital Razi", hospital: "Hôpital régional Kébili" },
  { id: 4, date: "Jeudi 19 février 2026", doctorName: "Dr Selima Jelili", affiliation: "Hôpital Razi", hospital: "Hôpital régional Kébili" },
  { id: 5, date: "Jeudi 05 mars 2026", doctorName: "Dr Melek Hajri", affiliation: "Médecin de libre pratique", hospital: "Hôpital régional Kébili" },
  { id: 6, date: "Jeudi 19 mars 2026", doctorName: "Dr Maissa Mtar", affiliation: "Hôpital Razi", hospital: "Hôpital régional Kébili" },
  { id: 7, date: "Jeudi 16 avril 2026", doctorName: "Dr Emna Cherif", affiliation: "Hôpital Razi", hospital: "Hôpital régional Tabarka" },
  { id: 8, date: "Jeudi 30 avril 2026", doctorName: "Dr Khaoula Ben Salem", affiliation: "Hôpital Habib Bougatfa Bizerte", hospital: "Hôpital régional Kasserine" },
  { id: 9, date: "Jeudi 7 mai 2026", doctorName: "Dr Manel Mziou", affiliation: "Hôpital Mongi Slim La Marsa", hospital: "Hôpital régional Kerkennah" },
  { id: 10, date: "Jeudi 14 mai 2026", doctorName: "Dr Imen Chaabene", affiliation: "Centre médecine scolaire et universitaire Tunis", hospital: "Hôpital régional Siliana" },
  { id: 11, date: "Jeudi 21 mai 2026", doctorName: "Dr Abir Ben Hamouda", affiliation: "Hôpital Mongi Slim La Marsa", hospital: "Hôpital régional Tabarka" },
  { id: 12, date: "Jeudi 28 mai 2026", doctorName: "Dr Syrine Ben Fraj", affiliation: "Hôpital régional Gafsa", hospital: "Hôpital régional Tataouine" },
  { id: 13, date: "Jeudi 04 juin 2026", doctorName: "Pr Fatma Charfi", affiliation: "Hôpital Mongi Slim La Marsa", hospital: "Hôpital régional Zaghouan" },
  { id: 14, date: "Jeudi 11 juin 2026", doctorName: "Dr Wael Askri", affiliation: "Hôpital Razi", hospital: "Hôpital régional Kébili" },
  { id: 15, date: "Jeudi 18 juin 2026", doctorName: "Dr Laures Meddouri", affiliation: "Hôpital Mongi Slim La Marsa", hospital: "Hôpital régional Kasserine" },
  { id: 16, date: "Jeudi 25 juin 2026", doctorName: "Dr Maha Hafnaoui", affiliation: "Médecin de libre pratique", hospital: "Hôpital régional Kerkennah" },
  { id: 17, date: "Jeudi 2 juillet 2026", doctorName: "Dr Maissa Mtar", affiliation: "Médecin de libre pratique", hospital: "Hôpital régional Siliana" },
  { id: 18, date: "Jeudi 9 juillet 2026", doctorName: "Dr Mariem Boudali", affiliation: "Médecin de libre pratique", hospital: "Hôpital régional Tabarka" },
  { id: 19, date: "Jeudi 16 juillet 2026", doctorName: "Dr Meriem Hammami", affiliation: "Médecin de libre pratique", hospital: "Hôpital régional Tataouine" },
  { id: 20, date: "Jeudi 23 juillet 2026", doctorName: "Dr Selma Cherif", affiliation: "Hôpital Razi", hospital: "Hôpital régional Zaghouan" },
  { id: 21, date: "Jeudi 30 juillet 2026", doctorName: "Dr Melek Hajri", affiliation: "Médecin de libre pratique", hospital: "Hôpital régional Kébili" },
  { id: 22, date: "Jeudi 06 août 2026", doctorName: "Dr Asma Zili", affiliation: "Hôpital régional Jendouba", hospital: "Hôpital régional Kasserine" },
  { id: 23, date: "Jeudi 20 août 2026", doctorName: "Dr Wiem Kamoun", affiliation: "Médecin de libre pratique", hospital: "Hôpital régional Kerkennah" },
  { id: 24, date: "Jeudi 27 août 2026", doctorName: "Dr Selima Ennaifer", affiliation: "Médecin de libre pratique", hospital: "Hôpital régional Siliana" },
  { id: 25, date: "Jeudi 03 septembre 2026", doctorName: "Pr Asma Bouden", affiliation: "Hôpital Razi", hospital: "Hôpital régional Tabarka" },
  { id: 26, date: "Jeudi 10 septembre 2026", doctorName: "Dr Ons Nouira", affiliation: "Médecin de libre pratique", hospital: "Hôpital régional Tataouine" },
  { id: 27, date: "Jeudi 17 septembre 2026", doctorName: "Dr Afef Mansouri", affiliation: "Médecin de libre pratique", hospital: "Hôpital régional Zaghouan" },
  { id: 28, date: "Jeudi 24 septembre 2026", doctorName: "Dr Melek Baccar", affiliation: "Hôpital régional Béja", hospital: "Hôpital régional Kébili" },
  { id: 29, date: "Jeudi 01 octobre 2026", doctorName: "Dr Amira Zaatir", affiliation: "Médecin de libre pratique", hospital: "Hôpital régional Kasserine" }
];
