import os
import time
import html
import requests

BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

X_URL = "https://api.x.com/2/tweets/search/recent"
QUERY = "from:DeItaone -is:retweet"
POLL_INTERVAL = 60

HEADERS_X = {
    "Authorization": f"Bearer {BEARER_TOKEN}"
}

last_seen_tweet_id = None


def log(*args):
    print(*args, flush=True)


def get_latest_tweets():
    params = {
        "query": QUERY,
        "max_results": 10,
        "tweet.fields": "created_at"
    }

    try:
        response = requests.get(X_URL, headers=HEADERS_X, params=params, timeout=20)
        log("STATUS X:", response.status_code)
        log("RISPOSTA X:", response.text[:1200])

        if response.status_code != 200:
            return []

        data = response.json()
        return data.get("data", [])

    except Exception as e:
        log("ERRORE X:", str(e))
        return []


def safe_int_tweet_id(tweet_id: str) -> int:
    try:
        return int(tweet_id)
    except Exception:
        return 0


def apply_style_markers(text: str) -> str:
    if not text:
        return ""

    escaped = html.escape(text, quote=False)
    escaped = escaped.replace("[B]", "<b>").replace("[/B]", "</b>")
    escaped = escaped.replace("[I]", "<i>").replace("[/I]", "</i>")
    escaped = escaped.replace("[U]", "<u>").replace("[/U]", "</u>")

    return escaped


def parse_claude_fields(content: str):
    title = "MACRO UPDATE"
    opening = ""
    body = ""

    try:
        if "TITLE:" in content and "OPENING:" in content and "BODY:" in content:
            title = content.split("TITLE:", 1)[1].split("OPENING:", 1)[0].strip()
            opening = content.split("OPENING:", 1)[1].split("BODY:", 1)[0].strip()
            body = content.split("BODY:", 1)[1].strip()
    except Exception:
        pass

    return title, opening, body


def is_relevant(tweet_text: str) -> bool:
    """
    Chiede a Claude se il tweet è rilevante per una delle categorie filtrate.
    Restituisce True solo se Claude risponde YES.
    """
    if not ANTHROPIC_API_KEY:
        return True  # se non c'è API key, lascia passare tutto

    prompt = f"""Sei un filtro editoriale per un canale macro istituzionale.

Valuta se questo tweet rientra in ALMENO UNA di queste categorie:

1. GEOPOLITICA — conflitti armati, sanzioni, escalation diplomatica, rischi sistemici globali
2. PREZZI — movimenti rilevanti su indici azionari, commodity, FX, tassi, crypto (almeno ±0.5% o notizia che causa movimento atteso)
3. DATI MACRO — rilascio o revisione di dati economici (CPI, NFP, GDP, PMI, PPI, retail sales, jobless claims, ecc.)
4. TRIMESTRALI — risultati earnings, EPS, revenue, guidance, outlook societario
5. BANCHE CENTRALI — decisioni su tassi, dichiarazioni di governatori, minutes, forward guidance (Fed, BCE, BOJ, BOE, SNB, RBA, ecc.)

Tweet:
"{tweet_text}"

Rispondi SOLO con:
YES — se rientra in almeno una categoria
NO — se è irrilevante, generico, commento senza impatto, notizia soft

Nessuna spiegazione. Solo YES o NO."""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",  # modello veloce per il filtro
                "max_tokens": 10,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )

        if response.status_code != 200:
            log("FILTRO CLAUDE errore status:", response.status_code)
            return True  # in caso di errore, lascia passare

        data = response.json()
        answer = data["content"][0]["text"].strip().upper()
        log("FILTRO:", answer, "→", tweet_text[:80])
        return answer.startswith("YES")

    except Exception as e:
        log("ERRORE FILTRO:", str(e))
        return True  # in caso di errore, lascia passare


def rewrite_tweet_with_claude(tweet_text: str):
    if not ANTHROPIC_API_KEY:
        return ("MACRO UPDATE", tweet_text, "")

    prompt = f"""Sei un macro strategist.

Trasforma questo tweet in un messaggio Telegram in italiano.

Tweet:
"{tweet_text}"

Formato output:

TITLE: titolo breve (max 4 parole, MAIUSCOLO)
OPENING: massimo 2 righe
BODY: massimo 5-6 righe

REGOLE CRITICHE:
- OGNI FRASE DEVE ANDARE A CAPO
- niente paragrafi lunghi
- niente blocchi compatti
- ritmo veloce, da desk

STILE:
- breve
- diretto
- ad alto impatto
- tono hedge fund / macro desk
- semplice ma autorevole
- niente spiegoni
- niente linguaggio giornalistico generico

FORMATTAZIONE:
- usa [B]...[/B] per concetti chiave
- usa [I]...[/I] per implicazioni
- usa [U]...[/U] solo per numeri, livelli, target o riferimenti quantitativi
- NON abusare del formatting
- bold e italic devono dare fluidità, non sembrare artificiali

VIETATO:
- niente emoji
- niente bullet points
- niente hashtag
- niente tag tipo POLICY | RISK
- niente frasi lunghe
- non inventare dati

OBIETTIVO:
deve sembrare un messaggio veloce che arriva su un desk trading.

Output SOLO nel formato richiesto."""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 600,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )

        log("STATUS CLAUDE:", response.status_code)
        log("RISPOSTA CLAUDE:", response.text[:1800])

        if response.status_code != 200:
            return ("MACRO UPDATE", tweet_text, "")

        data = response.json()
        content = data["content"][0]["text"].strip()
        return parse_claude_fields(content)

    except Exception as e:
        log("ERRORE CLAUDE:", str(e))
        return ("MACRO UPDATE", tweet_text, "")


def build_final_message(title: str, opening: str, body: str) -> str:
    clean_title = html.escape((title or "MACRO UPDATE").upper(), quote=False)
    header = f"🚨 <b>BREAKING NEWS | {clean_title}</b>"

    parts = [header]

    if opening:
        parts.append(apply_style_markers(opening))

    if body:
        parts.append(apply_style_markers(body))

    return "\n\n".join(parts)


def send_to_telegram(text: str):
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(telegram_url, data=payload, timeout=20)
        log("TELEGRAM STATUS:", response.status_code)
        log("TELEGRAM RESPONSE:", response.text[:1000])
        return response.status_code == 200
    except Exception as e:
        log("ERRORE TELEGRAM:", str(e))
        return False


log("BOT X AVVIATO — filtro attivo su geopolitica, prezzi, macro, earnings, banche centrali")

if not BEARER_TOKEN or not TELEGRAM_TOKEN or not CHANNEL_ID:
    raise ValueError("Manca X_BEARER_TOKEN, TELEGRAM_TOKEN o CHANNEL_ID")

# INVIO INIZIALE DELL'ULTIMO TWEET DISPONIBILE
initial_tweets = get_latest_tweets()

if initial_tweets:
    latest_tweet = initial_tweets[0]
    latest_tweet_id = latest_tweet["id"]
    latest_tweet_text = latest_tweet["text"]

    if is_relevant(latest_tweet_text):
        title, opening, body = rewrite_tweet_with_claude(latest_tweet_text)
        initial_message = build_final_message(title, opening, body)
        send_to_telegram(initial_message)
        log("INVIO INIZIALE EFFETTUATO.")
    else:
        log("INVIO INIZIALE SALTATO — tweet non rilevante.")

    last_seen_tweet_id = safe_int_tweet_id(latest_tweet_id)
    log("last_seen_tweet_id =", last_seen_tweet_id)
else:
    log("NESSUN TWEET TROVATO ALL'AVVIO")

# LOOP NORMALE
while True:
    tweets = get_latest_tweets()

    if tweets:
        tweets = list(reversed(tweets))

        for tweet in tweets:
            tweet_id_raw = tweet["id"]
            tweet_id = safe_int_tweet_id(tweet_id_raw)
            tweet_text = tweet["text"]

            if last_seen_tweet_id is None:
                last_seen_tweet_id = tweet_id
                continue

            if tweet_id > last_seen_tweet_id:
                log("NUOVO TWEET:", tweet_id)

                if is_relevant(tweet_text):
                    title, opening, body = rewrite_tweet_with_claude(tweet_text)
                    final_message = build_final_message(title, opening, body)
                    send_to_telegram(final_message)
                    log("INVIATO su Telegram.")
                else:
                    log("SCARTATO — non rilevante.")

                last_seen_tweet_id = tweet_id
            else:
                log("GIÀ VISTO:", tweet_id)

    time.sleep(POLL_INTERVAL)
