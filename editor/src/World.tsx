import { useEffect, useState } from "react"
import { type SessionState, type WorldAsset, api } from "./api"
import { Spinner, icons } from "./icons"

/** The cast and sets of the show. Each look is made once, approved here, and reused in every frame. */
export function WorldView({ state, onClose, onChanged }: { state: SessionState; onClose: () => void; onChanged: () => void }) {
  const [assets, setAssets] = useState<WorldAsset[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [stamp, setStamp] = useState(0)

  useEffect(() => {
    api.world(state.session_id).then((body) => setAssets(body.assets)).catch((reason: Error) => setError(reason.message))
  }, [state.session_id])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  const decide = (asset: WorldAsset, verdict: "approve" | "reopen") => {
    api
      .worldVerdict(state.session_id, asset.asset_id, verdict)
      .then((body) => {
        setAssets(body.assets)
        setStamp(Date.now())
        onChanged()
      })
      .catch((reason: Error) => setError(reason.message))
  }

  const groups: [string, WorldAsset[]][] = [
    ["Cast", (assets ?? []).filter((item) => item.kind === "character")],
    ["Sets", (assets ?? []).filter((item) => item.kind === "set")],
  ]

  return (
    <div className="scrim" onMouseDown={onClose}>
      <div className="settings world" role="dialog" aria-label="World" onMouseDown={(event) => event.stopPropagation()}>
        <header className="pane-head">
          <div className="pane-title">
            <strong>World</strong>
            <span className="muted">{state.episode.title}</span>
          </div>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>
            {icons.close}
          </button>
        </header>
        <div className="settings-body">
          <p className="muted">
            Every character and set is designed once and then animated. An approved look is locked: it stays the same in
            every shot of every episode until you make a new version of it.
          </p>
          {error ? <p className="note error">{error}</p> : null}
          {assets === null && !error ? <Spinner /> : null}
          {assets && assets.length === 0 ? (
            <p className="note">This project was opened without its world, so the stage shows stand-in shapes.</p>
          ) : null}
          {groups.map(([title, items]) =>
            items.length ? (
              <section key={title} className="world-group">
                <h3>{title}</h3>
                {items.map((asset) => (
                  <article key={asset.asset_id} className="world-card">
                    <img
                      src={`/api/sessions/${state.session_id}/world/${asset.asset_id}.png?v=${asset.digest}${stamp}`}
                      alt={asset.kind === "character" ? `Model sheet for ${asset.name}` : `The ${asset.name} set`}
                      loading="lazy"
                    />
                    {asset.candidates && asset.candidates.length > 1 ? (
                      <div className="candidates">
                        {asset.candidates.map((candidate, index) => (
                          <button
                            key={candidate.file}
                            className={index === asset.chosen ? "candidate chosen" : "candidate"}
                            disabled={asset.status === "approved" || index === asset.chosen}
                            title={asset.status === "approved" ? "Reopen the set to pick another picture" : "Use this picture for the set"}
                            onClick={() =>
                              api
                                .worldChoose(state.session_id, asset.asset_id, index)
                                .then((body) => {
                                  setAssets(body.assets)
                                  setStamp(Date.now())
                                  onChanged()
                                })
                                .catch((reason: Error) => setError(reason.message))
                            }
                          >
                            <img
                              src={`/api/sessions/${state.session_id}/world/${asset.asset_id}/candidates/${index}.png`}
                              alt={`Painted by ${candidate.by}`}
                              loading="lazy"
                            />
                            <span>
                              {candidate.by}
                              {index === asset.chosen ? " · in use" : ""}
                            </span>
                          </button>
                        ))}
                      </div>
                    ) : null}
                    <footer>
                      <div>
                        <strong>{asset.name}</strong>
                        <span className="muted">
                          Version {asset.version} · {asset.source}
                        </span>
                      </div>
                      <span className={asset.status === "approved" ? "status applied" : "status pending"}>
                        {asset.status === "approved" ? "Approved" : "Waiting for approval"}
                      </span>
                      {asset.status === "approved" ? (
                        <button className="btn small ghost" onClick={() => decide(asset, "reopen")}>
                          Reopen
                        </button>
                      ) : (
                        <button className="btn small primary" onClick={() => decide(asset, "approve")}>
                          {icons.check} Approve
                        </button>
                      )}
                    </footer>
                  </article>
                ))}
              </section>
            ) : null,
          )}
        </div>
      </div>
    </div>
  )
}
