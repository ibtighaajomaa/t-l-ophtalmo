import { useEffect, useRef } from "react";
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Bold,
  IndentDecrease,
  IndentIncrease,
  Italic,
  List,
  ListOrdered,
  Redo2,
  RemoveFormatting,
  Strikethrough,
  Underline,
  Undo2,
} from "lucide-react";

interface RichTextEditorProps {
  value: string;
  onChange: (value: string) => void;
}

type EditorCommand =
  | "bold"
  | "italic"
  | "underline"
  | "strikeThrough"
  | "insertOrderedList"
  | "insertUnorderedList"
  | "justifyLeft"
  | "justifyCenter"
  | "justifyRight"
  | "outdent"
  | "indent"
  | "removeFormat"
  | "undo"
  | "redo"
  | "formatBlock"
  | "foreColor";

const buttons: Array<{
  command: EditorCommand;
  label: string;
  icon: typeof Bold;
  divider?: boolean;
}> = [
  { command: "bold", label: "Gras", icon: Bold },
  { command: "italic", label: "Italique", icon: Italic },
  { command: "underline", label: "Souligné", icon: Underline },
  { command: "strikeThrough", label: "Barré", icon: Strikethrough, divider: true },
  { command: "insertOrderedList", label: "Liste numérotée", icon: ListOrdered },
  { command: "insertUnorderedList", label: "Liste à puces", icon: List },
  { command: "justifyLeft", label: "Aligner à gauche", icon: AlignLeft, divider: true },
  { command: "justifyCenter", label: "Centrer", icon: AlignCenter },
  { command: "justifyRight", label: "Aligner à droite", icon: AlignRight },
  { command: "outdent", label: "Diminuer le retrait", icon: IndentDecrease, divider: true },
  { command: "indent", label: "Augmenter le retrait", icon: IndentIncrease },
  { command: "removeFormat", label: "Effacer la mise en forme", icon: RemoveFormatting },
  { command: "undo", label: "Annuler", icon: Undo2, divider: true },
  { command: "redo", label: "Rétablir", icon: Redo2 },
];

function cleanGeneratedHtml(html: string) {
  const parsed = new DOMParser().parseFromString(html, "text/html");
  parsed.querySelectorAll("script, style, iframe, object, embed").forEach((node) => node.remove());
  parsed.body.querySelectorAll("*").forEach((element) => {
    for (const attribute of Array.from(element.attributes)) {
      if (attribute.name.startsWith("on")) element.removeAttribute(attribute.name);
    }
  });
  return parsed.body.innerHTML;
}

export function RichTextEditor({ value, onChange }: RichTextEditorProps) {
  const editorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (editorRef.current && editorRef.current.innerHTML !== value) {
      editorRef.current.innerHTML = cleanGeneratedHtml(value);
    }
  }, [value]);

  function runCommand(command: EditorCommand, commandValue?: string) {
    editorRef.current?.focus();
    document.execCommand(command, false, commandValue);
    if (editorRef.current) onChange(editorRef.current.innerHTML);
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-600 bg-[#121936]">
      <div className="flex flex-wrap items-center gap-1 border-b border-slate-600 bg-[#17203f] p-2">
        <select
          aria-label="Style du paragraphe"
          defaultValue="p"
          onChange={(event) => runCommand("formatBlock", event.target.value)}
          className="h-8 rounded border border-slate-600 bg-[#121936] px-2 text-xs text-slate-200 outline-none focus:border-blue-500"
        >
          <option value="p">Paragraphe</option>
          <option value="h2">Titre</option>
          <option value="h3">Sous-titre</option>
          <option value="blockquote">Citation</option>
        </select>

        {buttons.map(({ command, label, icon: Icon, divider }) => (
          <span key={command} className={divider ? "ml-1 border-l border-slate-600 pl-1" : ""}>
            <button
              type="button"
              title={label}
              aria-label={label}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => runCommand(command)}
              className="inline-flex h-8 w-8 items-center justify-center rounded text-slate-300 transition hover:bg-slate-600 hover:text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <Icon className="h-4 w-4" />
            </button>
          </span>
        ))}

        <label
          title="Couleur du texte"
          className="ml-1 flex h-8 cursor-pointer items-center gap-1 border-l border-slate-600 pl-2 text-[10px] text-slate-400"
        >
          Couleur
          <input
            type="color"
            defaultValue="#cbd5e1"
            aria-label="Couleur du texte"
            onChange={(event) => runCommand("foreColor", event.currentTarget.value)}
            className="h-5 w-6 cursor-pointer border-0 bg-transparent p-0"
          />
        </label>
      </div>

      <div
        ref={editorRef}
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-label="Éditeur du rapport clinique"
        aria-multiline="true"
        onInput={(event) => onChange(event.currentTarget.innerHTML)}
        className="min-h-64 p-4 text-sm leading-relaxed text-slate-200 outline-none
          [&_blockquote]:border-l-2 [&_blockquote]:border-blue-400 [&_blockquote]:pl-3
          [&_h2]:mb-2 [&_h2]:text-lg [&_h2]:font-bold [&_h2]:text-white
          [&_h3]:mb-1 [&_h3]:text-base [&_h3]:font-semibold [&_h3]:text-white
          [&_ol]:list-decimal [&_ol]:pl-6 [&_p]:mb-2 [&_ul]:list-disc [&_ul]:pl-6"
      />
      <div className="border-t border-slate-700 px-3 py-1.5 text-[10px] text-slate-500">
        Rapport modifiable — vérifiez le contenu clinique avant validation.
      </div>
    </div>
  );
}
