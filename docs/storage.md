# Your documents on disk

Every section is a folder named after it, and every document a file named after its
title:

```
documents/
├── Alice/
│   ├── Passport.jpg
│   ├── Blood test - 1.jpg      ← a document with two pages
│   └── Blood test - 2.pdf
├── Rex/
│   └── Vaccination card.jpg
└── .papelada/                  ← the app's own data (index, crop backups)
```

Renaming a document or a section in the app renames its files or folder. Two
documents with the same title in one section get `Title.jpg` and `Title (2).jpg`.
Names are kept valid on Windows and macOS too, so the folder works over a network share.

You're free to browse and copy anything in the volume and to add your own files to
it: Papelada never overwrites them. It ignores them until you tap **Scan for new files**
in the settings (the gear icon): every file in a section's folder it doesn't know
becomes a document titled after the file, dated from the file, and every new folder
at the top of the volume becomes a section. Scanning is unavailable while encryption is
on. Don't rename or move the files Papelada created by hand, though. It keeps track of them by name,
so do that from the app.

## Backups

Back up the documents folder: it holds everything, including `.papelada/`. If you
use encryption, back up the key separately.
