"""
pdf_search.py — Recherche plein texte dans des fichiers PDF
Interface graphique tkinter, extraction pdfplumber + OCR Tesseract en fallback.

Dépendances :
    pip install pdfplumber pillow pytesseract
    Tesseract doit être installé séparément :
      Windows : https://github.com/UB-Mannheim/tesseract/wiki
      Linux   : sudo apt install tesseract-ocr tesseract-ocr-fra
      macOS   : brew install tesseract

Optionnel (améliore la détection OCR) :
    pip install pdf2image
    + installer poppler : https://github.com/oschwartz10612/poppler-windows/releases (Windows)
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import re

# ── Imports optionnels ────────────────────────────────────────────────────────
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import pytesseract
    from PIL import Image
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    from pdf2image import convert_from_path
    HAS_PDF2IMAGE = True
except ImportError:
    HAS_PDF2IMAGE = False

# ── Couleurs & style ──────────────────────────────────────────────────────────
BG         = "#1e1e2e"
BG_PANEL   = "#2a2a3e"
BG_ENTRY   = "#12121c"
FG         = "#cdd6f4"
FG_DIM     = "#6c7086"
ACCENT     = "#89b4fa"
ACCENT2    = "#a6e3a1"
WARN       = "#f38ba8"
MATCH_BG   = "#313244"
FONT_MONO  = ("Consolas", 10)
FONT_UI    = ("Segoe UI", 10)
FONT_TITLE = ("Segoe UI", 13, "bold")

CONTEXT_CHARS = 120   # caractères avant/après le terme trouvé


# ── Extraction de texte ───────────────────────────────────────────────────────

def extract_text_pdfplumber(pdf_path: str) -> dict[int, str]:
    """Retourne {numéro_page: texte} via pdfplumber."""
    pages = {}
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages[i] = text
    return pages


def ocr_page_pdfplumber(pdf_path: str, page_num: int) -> str:
    """OCR d'une page via pdfplumber → image → Tesseract."""
    if not HAS_TESSERACT:
        return ""
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_num - 1]
        img = page.to_image(resolution=200).original
        return pytesseract.image_to_string(img, lang="fra+eng")


def ocr_pdf_pdf2image(pdf_path: str) -> dict[int, str]:
    """OCR de toutes les pages via pdf2image + Tesseract."""
    if not (HAS_PDF2IMAGE and HAS_TESSERACT):
        return {}
    images = convert_from_path(pdf_path, dpi=200)
    return {
        i + 1: pytesseract.image_to_string(img, lang="fra+eng")
        for i, img in enumerate(images)
    }


def get_pages_text(pdf_path: str, status_cb=None) -> dict[int, str]:
    """
    Extrait le texte de chaque page.
    - Si pdfplumber renvoie trop peu de texte (<20 car. / page), bascule en OCR.
    """
    if not HAS_PDFPLUMBER:
        raise RuntimeError("pdfplumber n'est pas installé.")

    pages = extract_text_pdfplumber(pdf_path)
    total_chars = sum(len(t) for t in pages.values())
    avg_chars   = total_chars / max(len(pages), 1)

    if avg_chars < 20:
        # PDF scanné → OCR
        if status_cb:
            status_cb(f"OCR en cours : {os.path.basename(pdf_path)}")
        if HAS_PDF2IMAGE:
            ocr_pages = ocr_pdf_pdf2image(pdf_path)
        elif HAS_TESSERACT:
            ocr_pages = {}
            for pnum in pages:
                ocr_pages[pnum] = ocr_page_pdfplumber(pdf_path, pnum)
        else:
            ocr_pages = {}
        # Fusionner : garder OCR si meilleur
        for pnum in pages:
            if len(ocr_pages.get(pnum, "")) > len(pages[pnum]):
                pages[pnum] = ocr_pages[pnum]

    return pages


# ── Recherche ─────────────────────────────────────────────────────────────────

def build_snippet(text: str, match: re.Match, ctx: int = CONTEXT_CHARS) -> str:
    """Extrait un extrait centré sur la correspondance."""
    start = max(0, match.start() - ctx)
    end   = min(len(text), match.end() + ctx)
    snippet = text[start:end].replace("\n", " ").strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def search_in_pdf(pdf_path: str, pattern: re.Pattern,
                  status_cb=None) -> list[dict]:
    """Retourne la liste des correspondances dans un fichier PDF."""
    results = []
    try:
        pages = get_pages_text(pdf_path, status_cb)
    except Exception as e:
        return [{"error": str(e), "file": pdf_path}]

    for pnum, text in pages.items():
        for match in pattern.finditer(text):
            results.append({
                "file":    pdf_path,
                "page":    pnum,
                "snippet": build_snippet(text, match),
                "term":    match.group(),
            })
    return results


def search_directory(directory: str, query: str,
                     case_sensitive: bool, use_regex: bool,
                     status_cb=None, progress_cb=None) -> list[dict]:
    """Parcourt récursivement un répertoire et cherche dans chaque PDF."""
    flags   = 0 if case_sensitive else re.IGNORECASE
    term    = query if use_regex else re.escape(query)
    try:
        pattern = re.compile(term, flags)
    except re.error as e:
        raise ValueError(f"Expression régulière invalide : {e}")

    pdf_files = []
    for root, _, files in os.walk(directory):
        for f in files:
            if f.lower().endswith(".pdf"):
                pdf_files.append(os.path.join(root, f))

    all_results = []
    for idx, path in enumerate(pdf_files, 1):
        if status_cb:
            status_cb(f"[{idx}/{len(pdf_files)}] {os.path.basename(path)}")
        if progress_cb:
            progress_cb(idx, len(pdf_files))
        all_results.extend(search_in_pdf(path, pattern, status_cb))

    return all_results


# ── Interface graphique ───────────────────────────────────────────────────────

class PdfSearchApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Recherche PDF")
        self.geometry("950x680")
        self.configure(bg=BG)
        self.resizable(True, True)
        self._build_ui()
        self._check_deps()

    # ── Construction UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        # Titre
        tk.Label(self, text="🔍  Recherche plein texte dans les PDFs",
                 bg=BG, fg=ACCENT, font=FONT_TITLE).pack(pady=(18, 4))

        # Bandeau dépendances
        self.dep_label = tk.Label(self, text="", bg=BG, fg=WARN,
                                  font=("Segoe UI", 9))
        self.dep_label.pack()

        # ── Panneau de contrôle ───────────────────────────────────────────────
        ctrl = tk.Frame(self, bg=BG_PANEL, pady=12, padx=16)
        ctrl.pack(fill="x", padx=16, pady=(8, 0))

        # Répertoire
        tk.Label(ctrl, text="Répertoire :", bg=BG_PANEL, fg=FG,
                 font=FONT_UI).grid(row=0, column=0, sticky="w")
        self.dir_var = tk.StringVar()
        dir_entry = tk.Entry(ctrl, textvariable=self.dir_var, width=60,
                             bg=BG_ENTRY, fg=FG, insertbackground=FG,
                             relief="flat", font=FONT_MONO)
        dir_entry.grid(row=0, column=1, padx=8, sticky="ew")
        tk.Button(ctrl, text="Parcourir…", command=self._pick_dir,
                  bg=ACCENT, fg=BG, relief="flat", font=FONT_UI,
                  cursor="hand2").grid(row=0, column=2)

        # Terme de recherche
        tk.Label(ctrl, text="Rechercher :", bg=BG_PANEL, fg=FG,
                 font=FONT_UI).grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.query_var = tk.StringVar()
        query_entry = tk.Entry(ctrl, textvariable=self.query_var, width=60,
                               bg=BG_ENTRY, fg=FG, insertbackground=FG,
                               relief="flat", font=FONT_MONO)
        query_entry.grid(row=1, column=1, padx=8, pady=(10, 0), sticky="ew")
        query_entry.bind("<Return>", lambda e: self._start_search())

        # Options
        opt = tk.Frame(ctrl, bg=BG_PANEL)
        opt.grid(row=2, column=1, sticky="w", pady=(6, 0))
        self.case_var  = tk.BooleanVar(value=False)
        self.regex_var = tk.BooleanVar(value=False)
        tk.Checkbutton(opt, text="Respecter la casse", variable=self.case_var,
                       bg=BG_PANEL, fg=FG, selectcolor=BG_ENTRY,
                       activebackground=BG_PANEL, font=FONT_UI).pack(side="left")
        tk.Checkbutton(opt, text="Regex", variable=self.regex_var,
                       bg=BG_PANEL, fg=FG, selectcolor=BG_ENTRY,
                       activebackground=BG_PANEL, font=FONT_UI).pack(side="left", padx=16)

        # Bouton recherche
        self.btn_search = tk.Button(ctrl, text="Lancer la recherche",
                                    command=self._start_search,
                                    bg=ACCENT2, fg=BG, relief="flat",
                                    font=("Segoe UI", 10, "bold"),
                                    cursor="hand2", padx=12)
        self.btn_search.grid(row=1, column=2, padx=(8, 0), pady=(10, 0))

        ctrl.columnconfigure(1, weight=1)

        # ── Barre de progression ──────────────────────────────────────────────
        prog_frame = tk.Frame(self, bg=BG)
        prog_frame.pack(fill="x", padx=16, pady=(6, 0))
        self.status_var = tk.StringVar(value="Prêt.")
        tk.Label(prog_frame, textvariable=self.status_var,
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 9),
                 anchor="w").pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(prog_frame, length=200,
                                        mode="determinate")
        self.progress.pack(side="right")

        # ── Zone de résultats ─────────────────────────────────────────────────
        res_frame = tk.Frame(self, bg=BG)
        res_frame.pack(fill="both", expand=True, padx=16, pady=10)

        self.result_count = tk.StringVar(value="")
        tk.Label(res_frame, textvariable=self.result_count,
                 bg=BG, fg=ACCENT2, font=("Segoe UI", 9, "bold"),
                 anchor="w").pack(anchor="w")

        cols = ("file", "page", "snippet")
        self.tree = ttk.Treeview(res_frame, columns=cols,
                                 show="headings", selectmode="browse")
        self.tree.heading("file",    text="Fichier")
        self.tree.heading("page",    text="Page")
        self.tree.heading("snippet", text="Extrait")
        self.tree.column("file",    width=220, stretch=False)
        self.tree.column("page",    width=60,  stretch=False, anchor="center")
        self.tree.column("snippet", width=600, stretch=True)

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Treeview", background=BG_PANEL, foreground=FG,
                        fieldbackground=BG_PANEL, rowheight=28,
                        font=FONT_MONO)
        style.configure("Treeview.Heading", background=BG_ENTRY,
                        foreground=ACCENT, font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", MATCH_BG)],
                  foreground=[("selected", ACCENT)])

        vsb = ttk.Scrollbar(res_frame, orient="vertical",
                            command=self.tree.yview)
        hsb = ttk.Scrollbar(res_frame, orient="horizontal",
                            command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.tree.pack(fill="both", expand=True)

        self.tree.bind("<Double-1>", self._open_file)

        # Pied de page
        tk.Label(self, text="Double-clic sur un résultat pour ouvrir le fichier PDF",
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 8)).pack(pady=(0, 6))

    # ── Vérification des dépendances ──────────────────────────────────────────

    def _check_deps(self):
        missing = []
        if not HAS_PDFPLUMBER:
            missing.append("pdfplumber")
        if not HAS_TESSERACT:
            missing.append("pytesseract + pillow")
        if not HAS_PDF2IMAGE:
            missing.append("pdf2image (optionnel, pour l'OCR)")
        if missing:
            self.dep_label.config(
                text="⚠  Manquant : " + ", ".join(missing) +
                     "  →  pip install " + " ".join(
                         [m.split(" ")[0] for m in missing]))

    # ── Actions ───────────────────────────────────────────────────────────────

    def _pick_dir(self):
        d = filedialog.askdirectory(title="Choisir un répertoire")
        if d:
            self.dir_var.set(d)

    def _start_search(self):
        directory = self.dir_var.get().strip()
        query     = self.query_var.get().strip()

        if not directory:
            messagebox.showwarning("Répertoire manquant",
                                   "Veuillez sélectionner un répertoire.")
            return
        if not os.path.isdir(directory):
            messagebox.showerror("Répertoire introuvable",
                                 f"Le répertoire n'existe pas :\n{directory}")
            return
        if not query:
            messagebox.showwarning("Terme vide",
                                   "Veuillez saisir un terme à rechercher.")
            return

        self.tree.delete(*self.tree.get_children())
        self.result_count.set("")
        self.btn_search.config(state="disabled")
        self.progress["value"] = 0

        thread = threading.Thread(target=self._run_search,
                                  args=(directory, query), daemon=True)
        thread.start()

    def _run_search(self, directory: str, query: str):
        def status(msg):
            self.status_var.set(msg)

        def progress(done, total):
            pct = int(done / total * 100) if total else 0
            self.progress["value"] = pct

        try:
            results = search_directory(
                directory, query,
                case_sensitive=self.case_var.get(),
                use_regex=self.regex_var.get(),
                status_cb=status,
                progress_cb=progress,
            )
        except ValueError as e:
            self.after(0, lambda: messagebox.showerror("Erreur", str(e)))
            self.after(0, lambda: self.btn_search.config(state="normal"))
            self.after(0, lambda: self.status_var.set("Erreur."))
            return

        self.after(0, lambda: self._display_results(results))

    def _display_results(self, results: list[dict]):
        errors  = [r for r in results if "error" in r]
        matches = [r for r in results if "error" not in r]

        for r in matches:
            fname = os.path.basename(r["file"])
            self.tree.insert("", "end",
                             values=(fname, r["page"], r["snippet"]),
                             tags=(r["file"],))

        n = len(matches)
        files = len({r["file"] for r in matches})
        self.result_count.set(
            f"{n} correspondance{'s' if n > 1 else ''} "
            f"dans {files} fichier{'s' if files > 1 else ''}"
            + (f"  —  {len(errors)} erreur(s)" if errors else "")
        )
        self.status_var.set("Recherche terminée.")
        self.progress["value"] = 100
        self.btn_search.config(state="normal")

        if errors:
            detail = "\n".join(f"{r['file']} : {r['error']}"
                               for r in errors[:5])
            messagebox.showwarning("Fichiers non traités",
                                   f"Certains PDFs n'ont pas pu être lus :\n{detail}")

    def _open_file(self, event):
        item = self.tree.focus()
        if not item:
            return
        values = self.tree.item(item, "values")
        if not values:
            return
        tags = self.tree.item(item, "tags")
        path = tags[0] if tags else None
        if not path or not os.path.isfile(path):
            return
        try:
            page = int(values[1])
        except (ValueError, IndexError):
            page = 1
        open_pdf_at_page(path, page)


# ── Ouverture PDF à une page précise ─────────────────────────────────────────

def open_pdf_at_page(path: str, page: int):
    """
    Tente d'ouvrir le PDF à la page indiquée.
    Stratégie : Adobe Acrobat/Reader → Foxit → SumatraPDF → fallback os.startfile.
    """
    import subprocess, shutil

    # ── Candidats lecteurs PDF avec leur syntaxe ──────────────────────────────
    # Chaque entrée : (executable_ou_chemin, [args...])
    # {path} et {page} seront remplacés dynamiquement.

    ADOBE_PATHS = [
        r"C:\Program Files (x86)\Adobe\Acrobat 11.0\Acrobat\Acrobat.exe",
        r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
        r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
        r"C:\Program Files\Adobe\Acrobat 2020\Acrobat\Acrobat.exe",
        r"C:\Program Files (x86)\Adobe\Reader 11.0\Reader\AcroRd32.exe",
    ]
    FOXIT_PATHS = [
        r"C:\Program Files\Foxit Software\Foxit PDF Reader\FoxitPDFReader.exe",
        r"C:\Program Files (x86)\Foxit Software\Foxit Reader\FoxitReader.exe",
    ]
    SUMATRA_PATHS = [
        r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
        r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
        shutil.which("SumatraPDF") or "",
    ]

    def try_adobe(exe):
        # /A "page=N" fonctionne avec Acrobat et Reader
        subprocess.Popen([exe, "/A", f"page={page}", path])

    def try_foxit(exe):
        subprocess.Popen([exe, "/A", f"page={page}", path])

    def try_sumatra(exe):
        subprocess.Popen([exe, "-page", str(page), path])

    candidates = (
        [(p, try_adobe)  for p in ADOBE_PATHS]
        + [(p, try_foxit)  for p in FOXIT_PATHS]
        + [(p, try_sumatra) for p in SUMATRA_PATHS]
    )

    for exe, launcher in candidates:
        if exe and os.path.isfile(exe):
            try:
                launcher(exe)
                return
            except Exception:
                continue

    # Aucun lecteur compatible trouvé → ouverture simple sans page précise
    os.startfile(path)


# ── Point d'entrée ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not HAS_PDFPLUMBER:
        import sys
        print("ERREUR : pdfplumber n'est pas installé.")
        print("Exécutez :  pip install pdfplumber pillow pytesseract pdf2image")
        sys.exit(1)

    app = PdfSearchApp()
    app.mainloop()
