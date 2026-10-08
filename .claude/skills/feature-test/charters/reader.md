# Charter: Reader (`/reader`)

## Persona

You are a second-year PhD student. On Thursday you present a short paper at
journal club. You read on an iPad with an Apple Pencil. You want to:

- finish the paper with every equation understood;
- leave with flashcards for the key results;
- have a list of open questions to raise;
- keep notes that link to this paper and to related ideas.

Your bar is what GoodNotes, Notability and PDF Expert do on an iPad, and what
Obsidian does for linked notes. Anything they make easy and this app does not
is a finding.

The fixture paper "Scaled Dot-Product Attention: A Short Derivation" (3 pages,
equations (1)-(5)) stands in for the real one.

## Charter items

**C1 Import.** Add the fixture PDF with "Add PDF" (file upload).
- It appears under Papers with its title from the PDF metadata and its page count.
- It opens at page 1.
- `__wa.serverItems('doc')` shows it.
- Reload: it is still there.

**C2 Reading.**
- Scroll to page 3; the page box updates.
- Type a page number to jump.
- Zoom in, zoom out and Fit change the page width, and the text stays sharp.
- Reload: the paper reopens near the last page read.

**C3 Pen and finger.** Pen tool active.
- A pen stroke draws ink on the page and survives reload.
- A finger stroke (`'touch'`) draws nothing.
- With the Erase tool, a pen pass over a stroke removes it, and the removal
  survives reload.
- The highlighter draws translucent ink.

**C4 Text selection actions.** Select tool active. Select "the square root of
the key" on page 1.
- An action bar appears near the selection, with Highlight, Comment, To
  notebook, Card, Explain, Follow-up, Question and Copy link.
- Highlight creates a visible highlight and a mark in the Marks panel.
- Tapping the highlight later reopens actions for that mark.

**C5 Comment and follow-up.** On a mark:
- Comment saves text that shows in the Marks panel.
- Follow-up creates a task that appears in Study, under "Open follow-ups", with
  a link back to the page.
- Following that link scrolls to the mark.

**C6 Question for journal club.**
- Mark the "Open question for discussion" sentence on page 3 as a Question.
- It appears in Study, under "Questions for journal club".

**C7 Region and equation card.** Region tool, then drag around equation (3) on
page 2.
- Region actions appear.
- Equation card opens a card editor.
- With an AI key: the LaTeX and the drafted question match the equation.
- Without a key: a clear error appears and the card can still be written and
  saved by hand.
- Saved cards appear in Study as due.

**C8 Explain.** Select the sentence about softmax saturating, then choose Explain.
- With an AI key: an explanation appears under "Explanations to read". It
  should be correct and actually help, with prerequisites, symbols and a check
  question.
- "Save as note" creates a note that links back to the passage.
- Without a key: the task shows the error and offers Retry.

**C9 Card review.**
- Start a review of the due cards.
- Show answer; grade with the buttons and with keys 1-4.
- The intervals shown on the buttons are plausible.
- After the last card, a done state appears.
- Graded cards are no longer due.

**C10 Paper notebook.** Open Notebook beside the PDF.
- Use "To notebook" on a selection: the quote plus a link to the passage
  appears in the notebook.
- Add a text block with Markdown and `$\sqrt{d_k}$`; it renders.
- Add an ink block and draw in it.
- Click the passage link: the PDF scrolls to it.

**C11 Linked notes.** Make a new note titled "Softmax saturation".
- Typing `[[Scal` suggests the paper; accepting it inserts the link.
- A link to a note that does not exist yet (`[[Temperature scaling]]`) renders
  as missing, and clicking it creates that note.
- The paper's Marks panel lists the note under "Linked notes".
- The note's panel shows its links and backlinks.

**C12 Ink to LaTeX and SymPy.** Only with an AI key: "To LaTeX" on a
handwritten ink block. Synthetic strokes are not real math, so judge only
that the flow handles the result sensibly.
- "Check with SymPy" loads and reports per line, or explains why it cannot.

**C13 Search.**
- Search for "saturat": it finds the paper text you marked, the note, and the
  tasks.
- Clicking a result opens it.

**C14 Empty notes.**
- Click "New note", then leave without typing. Try leaving inside the app,
  then try again with a reload.
- No "Untitled" note remains in the list or on the server.
- A new note that you type into is kept.

**C16 Understanding state.**
- Explain on a passage marks it "Not clear yet": a red "?" badge on the page,
  and a tag in the Marks panel.
- The panel's "Not clear yet" filter lists only those passages.
- On a mark, "Understood" clears it.
- "I understand it now" on an explanation also marks its passage understood.
- In Study, Retry or Generate on an explanation works without leaving Study.

**C17 Brief for journal club.**
- The paper's Brief collects questions with their passages, "Not clear yet"
  points with their explanation state, key equations with card counts, open
  follow-ups, comments, and the paper notebook's text.
- Page links in it jump to the passage.
- "Copy as Markdown" puts the same content on the clipboard.
- Judge it as the persona: could you present from it on Thursday?

**C18 iPad portrait layout.**
- At iPad portrait width the toolbar is one row.
- The Marks panel can always be closed: with its x button, with Escape, and
  after a reload.
- Jumping to a passage leaves it visible below the toolbar.
- The sync state stays visible in the header.

**C19 Table-stakes basics.**
- Undo and redo:
  - toolbar buttons, Cmd+Z / Shift+Cmd+Z;
  - two-finger tap to undo, three-finger tap to redo;
  - covers pen strokes, erasing, clear page, highlights, and marks with
    their cards and tasks;
  - works in notebook ink pads too.
- The eraser removes ink and plain highlights. "Clear page" appears with the
  eraser, and can be undone.
- Pen and highlighter come in three sizes.
- Pinch zoom (ctrl+wheel in the test browser) zooms the page, not the
  interface.
- The Contents panel lists chapters and sections and jumps to them.
- A paper can be renamed. Removing one moves it to Recently deleted, where
  it can be restored or deleted for good; re-adding the same PDF restores it.
- Find in paper (Contents, Cmd+F): Enter / Shift+Enter step through matches
  with an "i of n" count. Library search also finds text inside papers.
- The notebook beside or under the PDF resizes with its handle and keeps the
  size after a reload.
- Explanations stream in: watch Study while one is written.
- "Add to Brief" pins any passage or equation to the Brief.
- Lasso selects ink to move, resize or delete it (undoable), on pages and in
  notebook pads.
- Contents has page thumbnails and bookmarks (bookmarked pages show a
  ribbon).
- "Export with annotations" (paper menu, Brief) gives a PDF with ink and
  highlights drawn in; open it to check that the marks line up.
- Report anything else a GoodNotes or PDF Expert user would reach for and
  not find.

**C15 Sync and errors.**
- Throughout, the sync status ends at "Synced".
- The console has no uncaught errors.
- Everything you made is in `__wa.serverItems()` with the right kinds.

## Exploratory focus

Prepare for Thursday using only the reader:

- Can you build a one-page set of talking points?
- Is it easy to find every open question again?
- Is it clear which equations you have not understood yet?
- Report what slowed you down or what you expected to exist and did not.
