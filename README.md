<p align="center">
  <a href="https://www.gustavofurtado.com/papelada/"><img src="https://www.gustavofurtado.com/assets/img/projects/papelada.png" alt="Papelada" width="640"></a>
</p>

<p align="center">
  <b>A self-hosted home for your household's paperwork.</b>
</p>

<p align="center">
  <a href="https://github.com/GusFurtado/papelada/releases"><img src="https://img.shields.io/github/v/release/GusFurtado/papelada" alt="Release"></a>
  <a href="https://github.com/GusFurtado/papelada/pkgs/container/papelada"><img src="https://img.shields.io/badge/image-ghcr.io-2496ED?logo=docker&logoColor=white" alt="Docker image"></a>
  <a href="https://github.com/GusFurtado/papelada/actions/workflows/ci.yml"><img src="https://github.com/GusFurtado/papelada/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/GusFurtado/papelada/blob/main/LICENSE"><img src="https://img.shields.io/github/license/GusFurtado/papelada" alt="License"></a>
</p>

<p align="center">
  <b><a href="https://www.gustavofurtado.com/papelada/">Documentation</a></b>
</p>

IDs, exam results, receipts, contracts, vaccination cards: photograph a document with your phone
(or upload any file), file it under a section you created, tag it, and find it again later.
*Papelada* is Portuguese for "paperwork", or more precisely "a pile of papers".

## Installation

You need Docker with Compose.

```sh
mkdir papelada && cd papelada
curl -O https://raw.githubusercontent.com/GusFurtado/papelada/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/GusFurtado/papelada/main/.env.example
mkdir documents
docker compose up -d
```

Then open http://localhost:8080. The settings in `.env` are explained in the
[installation guide](https://www.gustavofurtado.com/papelada/installation/).

## Features

- **Your own sections and tags**: one section per person, pet, car or house, and tags across them.
- **Multi-page documents** straight from the phone camera, plus PDFs and any other file.
- **Plain files you can browse**: the volume is an ordinary folder tree with readable names.
- **Optional encryption at rest**, with the key kept out of the volume.
- **Optional login** for one user, set with two environment variables.
- One small container, no database, no third-party requests. English and Brazilian Portuguese.
