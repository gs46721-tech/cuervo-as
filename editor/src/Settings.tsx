import { useEffect, useState } from "react"
import { type KeyCheck, type ServiceKey, api } from "./api"
import { Spinner, icons } from "./icons"

/** Where each person connects their own model and voice accounts. Keys stay on this machine. */
export function Settings({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const [services, setServices] = useState<ServiceKey[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.keys().then((body) => setServices(body.services)).catch((reason: Error) => setError(reason.message))
  }, [])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  return (
    <div className="scrim" onMouseDown={onClose}>
      <div className="settings" role="dialog" aria-label="Accounts and keys" onMouseDown={(event) => event.stopPropagation()}>
        <header className="pane-head">
          <div className="pane-title">
            <strong>Accounts and keys</strong>
          </div>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>
            {icons.close}
          </button>
        </header>
        <div className="settings-body">
          <p className="muted">
            Connect your own accounts. Keys are saved in a private file on this computer and are sent only to the
            service they belong to. They are never put in an episode or shown again in full.
          </p>
          {error ? <p className="note error">{error}</p> : null}
          {services === null && !error ? <Spinner /> : null}
          {services?.map((service) => (
            <ServiceCard
              key={service.name}
              service={service}
              onSaved={(next) => {
                setServices(next)
                onChanged()
              }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function ServiceCard({ service, onSaved }: { service: ServiceKey; onSaved: (services: ServiceKey[]) => void }) {
  const [key, setKey] = useState("")
  const [model, setModel] = useState(service.model)
  const [base, setBase] = useState(service.base_url)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<KeyCheck | null>(null)
  const dirty = key.trim() !== "" || model !== service.model || base !== service.base_url

  const run = async (work: () => Promise<{ services: ServiceKey[] }>, test: boolean) => {
    setBusy(true)
    setResult(null)
    try {
      onSaved((await work()).services)
      setKey("")
      if (test) {
        setResult(await api.testKey(service.name))
      }
    } catch (reason) {
      setResult({ ok: false, message: reason instanceof Error ? reason.message : "That did not work." })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      className="service"
      onSubmit={(event) => {
        event.preventDefault()
        void run(
          () => api.saveKey(service.name, { api_key: key.trim() ? key.trim() : undefined, model, base_url: service.needs_base ? base : undefined }),
          true,
        )
      }}
    >
      <div className="service-head">
        <div>
          <strong>{service.label}</strong>
          <span className="muted">{service.role}</span>
        </div>
        <span className={service.connected ? "status applied" : "status"}>
          {service.connected ? `Connected ${service.key_hint}` : "Not connected"}
        </span>
      </div>
      <label>
        <span>API key</span>
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          placeholder={
            service.key_source === "environment"
              ? `Set in the shell (${service.key_hint}). Paste a key to use yours instead.`
              : service.connected
                ? `Saved (${service.key_hint}). Paste a new key to replace it.`
                : "Paste your key"
          }
          onChange={(event) => setKey(event.target.value)}
        />
      </label>
      {service.needs_base ? (
        <label>
          <span>Base URL</span>
          <input value={base} placeholder="https://your-endpoint/v1" spellCheck={false} onChange={(event) => setBase(event.target.value)} />
        </label>
      ) : null}
      <label>
        <span>Model</span>
        <input value={model} placeholder="Default" spellCheck={false} onChange={(event) => setModel(event.target.value)} />
      </label>
      <div className="service-foot">
        <button type="submit" className="btn small primary" disabled={busy || !dirty}>
          {busy ? <Spinner /> : null} Save and test
        </button>
        <button
          type="button"
          className="btn small"
          disabled={busy || !service.connected}
          onClick={() => {
            setBusy(true)
            setResult(null)
            api
              .testKey(service.name)
              .then(setResult)
              .catch((reason: Error) => setResult({ ok: false, message: reason.message }))
              .finally(() => setBusy(false))
          }}
        >
          Test
        </button>
        {service.key_source === "saved" ? (
          <button type="button" className="btn small ghost" disabled={busy} onClick={() => void run(() => api.removeKey(service.name), false)}>
            Disconnect
          </button>
        ) : null}
        {service.key_url ? (
          <a className="link spacer" href={service.key_url} target="_blank" rel="noreferrer">
            Get a key
          </a>
        ) : null}
      </div>
      {result ? <p className={result.ok ? "note ok" : "note error"}>{result.message}</p> : null}
      {result?.voices?.length ? (
        <details className="voices">
          <summary>Voice ids for your series kit</summary>
          <ul>
            {result.voices.map((voice) => (
              <li key={voice.voice_id}>
                <span>{voice.name}</span>
                <code>{voice.voice_id}</code>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </form>
  )
}
