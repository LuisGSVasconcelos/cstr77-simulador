# Deploy público — alternativas ao Streamlit Community Cloud

O Community Cloud (share.streamlit.io) tem um **quirk de visibilidade** que pode
deixar o app **privado** mesmo com "Public and searchable" marcado (o servidor
devolve 303 → login para quem não está autenticado). Se isso acontecer, use um
dos dois caminhos abaixo — ambos dão **URL pública garantida** sem precisar de
login do visitante.

---

## Opção A — Render (recomendado; você já usa)

O `render.yaml` acompanha este repositório. Render **auto-deploya a partir do
GitHub** e libera uma URL pública `https://<nome>.onrender.com`.

**Passos:**
1. Entre em https://dashboard.render.com (login com o GitHub `LuisGSVasconcelos`).
2. **New → Web Service**.
3. **Conecte o repositório** `LuisGSVasconcelos/cstr77-simulador`.
4. Escolha **`render.yaml`** quando perguntado ("Render Blueprint") — ou, se
   preferir manual, use:
   - **Name**: `cstr77-simulador`
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
   - **Plan**: Free
   - **Health Check Path**: `/_stcore/health`
5. **Create Web Service** → aguarde o deploy (~1–3 min).
6. URL final: **`https://cstr77-simulador.onrender.com`** (pública).

> Render free "adormece" o app após ~15 min sem uso; ao abrir, o primeiro
> carregamento demora ~30–60 s até acordar. Para a sala, vale o free tier.

---

## Opção B — Hugging Face Spaces (Streamlit)

Publicado por padrão, sem quirk de visibilidade.

**Passos:**
1. Entre em https://huggingface.co/new-space com o GitHub `LuisGSVasconcelos`.
2. Preencha:
   - **Owner**: `LuisGSVasconcelos`
   - **Space name**: `cstr77-simulador`
   - **SDK**: **Streamlit**
3. **Create Space** → depois suba os arquivos (drag & drop na aba *Files*):
   - `app.py`
   - `simulador_cstr77.py`
   - `requirements.txt`
4. Espera o build (~1 min). URL final: **`https://huggingface.co/spaces/LuisGSVasconcelos/cstr77-simulador`**.

> Para sincronizar automaticamente com este repositório, dê `git push` no remote
> do Space (`https://huggingface.co/spaces/LuisGSVasconcelos/cstr77-simulador`).
> A UI bastapara começar; o git evita subir manualmente cada arquivo.

---

## Como confirmar que está público (de qualquer lugar)

Independente da plataforma, o `/health` do Streamlit responde `ok` quando o app
está no ar e público:

```bash
curl https://<URL-do-seu-app>/_stcore/health   # esperado: "ok"
```

Se responder com um `303 → login`, o app está **privado** (o problema do Community
Cloud); se der *timeout/502*, ainda está em build ou dormindo.