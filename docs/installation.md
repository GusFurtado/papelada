# Installation

You need Docker with Compose.

```sh
mkdir papelada && cd papelada
curl -O https://raw.githubusercontent.com/GusFurtado/papelada/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/GusFurtado/papelada/main/.env.example
mkdir documents          # or point DOCUMENTS_PATH in .env at an existing folder
docker compose up -d
```

Then open http://localhost:8080.

Create the documents folder yourself before starting. If Docker creates it, it
belongs to root, and Papelada (which never runs as root) can't write to it.

`latest` is the newest release. To stay on one version, use its tag instead, e.g.
`ghcr.io/gusfurtado/papelada:0.1.0`, or `:0.1` to also get its 0.1.x bug-fix releases.

## Configuration

Set these in `.env`, next to `docker-compose.yml`:

| Variable         | Default       | What it does                                                                        |
|------------------|---------------|-------------------------------------------------------------------------------------|
| `DOCUMENTS_PATH` | `./documents` | Folder on the host where your documents are kept (the volume).                      |
| `PORT`           | `8080`        | Port Papelada is served on.                                                         |
| `PUID` / `PGID`  | `1000`        | User and group the app runs as, which own every file it writes. Use `id -u` / `id -g`. |
| `ENCRYPTION_KEY` | *(empty)*     | Enables encryption. See [Encryption](encryption.md).                                                      |
| `USERNAME`       | *(empty)*     | Login name. Together with `PASSWORD`, turns the login on. See [Security](security.md). |
| `PASSWORD`       | *(empty)*     | Login password.                                                                     |

To use a Docker secret instead of an environment variable, set `ENCRYPTION_KEY_FILE`
or `PASSWORD_FILE` to the secret's path inside the container.

`docker compose` also reads variables from your shell, and they win over `.env`. If
your shell exports a `USERNAME` of its own, Papelada will refuse to start (it has no
`PASSWORD`) until you unset it or give it one.
