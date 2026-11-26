import { useEffect, useState } from "react"
import { type KeyCheck, type Role, type RoleEntry, type ServiceKey, api } from "./api"
import { Spinner, icons } from "./icons"

/** Where each person connects their own model and voice accounts. Keys stay on this machine. */
export function Settings({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const [services, setServices] = useState<ServiceKey[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<"accounts" | "roles">("accounts")

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
      <div className="settings" role="dialog" aria-label="Accounts and models" onMouseDown={(event) => event.stopPropagation()}>
        <header className="pane-head">
          <div className="pane-title">
            <strong>Accounts and models</strong>
          </div>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>
            {icons.close}
          </button>
        </header>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "accounts"} onClick={() => setTab("accounts")}>
            Accounts
          </button>
          <button role="tab" aria-selected={tab === "roles"} onClick={() => setTab("roles")}>
            Who does what
          </button>
        </div>
        {tab === "roles" ? <Roles services={services ?? []} onChanged={onChanged} /> : null}
        <div className="settings-body" hidden={tab !== "accounts"}>
          <p className="muted">
            Connect your own accounts. Keys are saved in a private file on this computer and are sent only to the
            service they belong to. They are never put in an episode or shown again in full.
          </p>
          {error ? <p className="note error">{error}</p> : null}
          {services === null && !error ? <Spinner /> : null}
          {services ? <h3 className="settings-group">On this computer</h3> : null}
          {services ? (
            <p className="muted">
              Agents you already use. They work through the account you are signed in to, so there is no key to paste.
            </p>
          ) : null}
          {services
            ?.filter((service) => service.kind === "local")
            .map((service) => (
              <LocalCard
                key={service.name}
                service={service}
                onSaved={(next) => {
                  setServices(next)
                  onChanged()
                }}
              />
            ))}
          {services ? <h3 className="settings-group">With an API key</h3> : null}
          {services
            ?.filter((service) => service.kind !== "local")
            .map((service) => (
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


function LocalCard({ service, onSaved }: { service: ServiceKey; onSaved: (services: ServiceKey[]) => void }) {
  const [model, setModel] = useState(service.model)
  const [path, setPath] = useState(service.base_url)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<KeyCheck | null>(null)
  const dirty = model !== service.model || path !== service.base_url

  const test = () => {
    setBusy(true)
    setResult(null)
    api
      .testKey(service.name)
      .then(setResult)
      .catch((reason: Error) => setResult({ ok: false, message: reason.message }))
      .finally(() => setBusy(false))
  }

  return (
    <form
      className="service"
      onSubmit={(event) => {
        event.preventDefault()
        setBusy(true)
        setResult(null)
        api
          .saveKey(service.name, { model, base_url: path })
          .then((body) => onSaved(body.services))
          .catch((reason: Error) => setResult({ ok: false, message: reason.message }))
          .finally(() => setBusy(false))
      }}
    >
      <div className="service-head">
        <div>
          <strong>{service.label}</strong>
          <span className="muted">
            {service.connected ? `Found: ${service.version || "installed"}` : "Not found on this computer."}
          </span>
        </div>
        <span className={service.connected ? "status applied" : "status"}>{service.connected ? "Installed" : "Not installed"}</span>
      </div>
      <label>
        <span>Model</span>
        <input value={model} placeholder="The agent's own default" spellCheck={false} onChange={(event) => setModel(event.target.value)} />
      </label>
      <label>
        <span>Program</span>
        <input value={path} placeholder="Found automatically. Set a path if it is not." spellCheck={false} onChange={(event) => setPath(event.target.value)} />
      </label>
      <div className="service-foot">
        <button type="submit" className="btn small primary" disabled={busy || !dirty}>
          Save
        </button>
        <button type="button" className="btn small" disabled={busy || !service.connected} title="Sends one short real request" onClick={test}>
          {busy ? <Spinner /> : null} Test
        </button>
        {!service.connected && service.key_url ? (
          <a className="link spacer" href={service.key_url} target="_blank" rel="noreferrer">
            Get {service.label}
          </a>
        ) : null}
      </div>
      {result ? <p className={result.ok ? "note ok" : "note error"}>{result.message}</p> : null}
      {!result && service.connected ? <p className="muted">If the test says it is not signed in: {service.login_hint}</p> : null}
    </form>
  )
}

/** Pick the models for each job, and whether they take turns or compete. */
function Roles({ services, onChanged }: { services: ServiceKey[]; onChanged: () => void }) {
  const [roles, setRoles] = useState<Role[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [models, setModels] = useState<Record<string, string[]>>({})

  useEffect(() => {
    api.roles().then((body) => setRoles(body.roles)).catch((reason: Error) => setError(reason.message))
  }, [])
  // Ask each connected account which models it has, to offer them as you type.
  const connected = services.filter((item) => item.connected && item.name !== "elevenlabs").map((item) => item.name).join(",")
  useEffect(() => {
    for (const name of connected.split(",").filter(Boolean)) {
      api
        .testKey(name)
        .then((result) => setModels((current) => ({ ...current, [name]: result.models ?? [] })))
        .catch(() => undefined)
    }
  }, [connected])

  return (
    <div className="settings-body">
      <p className="muted">
        Give each job to the model that is best at it. Put more than one model on a job and they can take turns, or
        compete: each one does the work and the best result is kept.
      </p>
      {error ? <p className="note error">{error}</p> : null}
      {roles === null && !error ? <Spinner /> : null}
      {roles?.map((role) => (
        <RoleCard
          key={role.role + JSON.stringify(role.entries) + role.compete + JSON.stringify(role.judge)}
          role={role}
          models={models}
          judges={roles.find((item) => item.role === "review")?.choices ?? []}
          onSaved={(next) => {
            setRoles(next)
            onChanged()
          }}
        />
      ))}
    </div>
  )
}

function RoleCard({
  role,
  models,
  judges,
  onSaved,
}: {
  role: Role
  models: Record<string, string[]>
  judges: Role["choices"]
  onSaved: (roles: Role[]) => void
}) {
  const [entries, setEntries] = useState<RoleEntry[]>(role.entries)
  const [compete, setCompete] = useState(role.compete)
  const [judge, setJudge] = useState<RoleEntry | null>(role.judge)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const image = role.role === "image"
  const dirty =
    JSON.stringify(entries) !== JSON.stringify(role.entries) || compete !== role.compete || JSON.stringify(judge) !== JSON.stringify(role.judge)

  const save = (body: { entries: RoleEntry[]; compete: boolean; judge: RoleEntry | null }) => {
    setBusy(true)
    setError(null)
    api
      .saveRole(role.role, body)
      .then((result) => onSaved(result.roles))
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setBusy(false))
  }
  const change = (index: number, patch: Partial<RoleEntry>) =>
    setEntries(entries.map((entry, position) => (position === index ? { ...entry, ...patch } : entry)))

  return (
    <form
      className="service"
      onSubmit={(event) => {
        event.preventDefault()
        save({ entries, compete: compete && entries.length > 1, judge: compete && !image ? judge : null })
      }}
    >
      <div className="service-head">
        <div>
          <strong>{role.label}</strong>
          <span className="muted">{role.help}</span>
        </div>
        <span className="status">{role.custom ? "Your choice" : "Default"}</span>
      </div>
      {entries.length === 0 ? (
        <p className="muted">{image ? "No image model. Sets are drawn in the built-in house style." : "No model chosen."}</p>
      ) : null}
      {entries.map((entry, index) => {
        const choice = role.choices.find((item) => item.name === entry.provider)
        return (
          <div className="role-row" key={index}>
            <span className="muted">{compete && entries.length > 1 ? "•" : `${index + 1}.`}</span>
            <select aria-label="Account" value={entry.provider} onChange={(event) => change(index, { provider: event.target.value, model: "" })}>
              {role.choices.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                  {item.available ? "" : " (not connected)"}
                </option>
              ))}
            </select>
            <input
              aria-label="Model"
              list={`models-${role.role}-${index}`}
              value={entry.model}
              placeholder={choice?.model ? `Default (${choice.model})` : "Default model"}
              spellCheck={false}
              onChange={(event) => change(index, { model: event.target.value })}
            />
            <datalist id={`models-${role.role}-${index}`}>
              {(models[entry.provider] ?? []).map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
            <button type="button" className="icon-btn" title="Remove" onClick={() => setEntries(entries.filter((_, position) => position !== index))}>
              {icons.close}
            </button>
          </div>
        )
      })}
      <div className="service-foot">
        <button
          type="button"
          className="btn small"
          disabled={entries.length >= 6 || role.choices.length === 0}
          onClick={() => setEntries([...entries, { provider: role.choices.find((item) => item.available)?.name ?? role.choices[0].name, model: "" }])}
        >
          {icons.plus} Add a model
        </button>
        <div className="segmented" role="group" aria-label="How the models share the job">
          <button type="button" aria-pressed={!compete} title="Use the first one. The next steps in only if it fails." onClick={() => setCompete(false)}>
            Take turns
          </button>
          <button
            type="button"
            aria-pressed={compete}
            disabled={entries.length < 2}
            title={image ? "Each model paints the set and you pick in World" : "Each model does the work and a judge keeps the best"}
            onClick={() => setCompete(true)}
          >
            Compete
          </button>
        </div>
      </div>
      {compete && entries.length > 1 && !image ? (
        <div className="role-row">
          <span className="muted">Judge</span>
          <select
            aria-label="Judge"
            value={judge?.provider ?? ""}
            onChange={(event) => setJudge(event.target.value ? { provider: event.target.value, model: "" } : null)}
          >
            <option value="">The review model</option>
            {judges.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
          <input
            aria-label="Judge model"
            value={judge?.model ?? ""}
            disabled={!judge}
            placeholder="Default model"
            spellCheck={false}
            onChange={(event) => judge && setJudge({ ...judge, model: event.target.value })}
          />
          <span />
        </div>
      ) : null}
      {compete && entries.length > 1 ? (
        <p className="muted">
          {image
            ? "Every model paints each new set. You pick the one to use in World."
            : "Every model answers. Answers in the wrong form are dropped, and the judge keeps the best of the rest. This costs one call per model, plus the judge."}
        </p>
      ) : null}
      <div className="service-foot">
        <button type="submit" className="btn small primary" disabled={busy || !dirty}>
          {busy ? <Spinner /> : null} Save
        </button>
        {role.custom ? (
          <button type="button" className="btn small ghost" disabled={busy} onClick={() => save({ entries: [], compete: false, judge: null })}>
            Back to default
          </button>
        ) : null}
      </div>
      {error ? <p className="note error">{error}</p> : null}
    </form>
  )
}
