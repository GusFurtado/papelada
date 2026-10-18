# Encryption

By default, documents are plain files, which is what makes the volume browsable.
That also means anyone who can read the volume, or its backups, can read your
documents.

To encrypt them, generate a key and add it to `.env`:

```sh
openssl rand -base64 32 | tr '+/' '-_'
```

Restart (`docker compose up -d`), then tap the lock icon in the app and choose
**Encrypt everything**. Every file moves from the section folders into
`.papelada/vault/` and is encrypted, along with the index of titles, tags and
dates, so nothing readable is left in the volume. **Decrypt everything** puts it all
back. Both take effect for existing and new documents, and an interrupted switch
finishes by itself on the next start.

**Keep a copy of the key somewhere safe, outside the documents folder.** Without it,
encrypted documents can't be recovered, and Papelada refuses to start without the
right key once the library is encrypted. Keeping the key out of the volume is the
point: a backup of the volume alone doesn't contain it.
