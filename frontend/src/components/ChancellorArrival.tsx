export type PresentationStage = "idle" | "arriving" | "presented" | "departing";

export function ChancellorArrival({ stage, onSkip }: { stage: PresentationStage; onSkip: () => void }) {
  if (stage === "idle") return null;
  return <div className={`arrival-layer ${stage}`} aria-live="polite">
    {stage === "arriving" && <button type="button" className="skip-arrival" onClick={onSkip}>跳过呈奏</button>}
    <div className="arrival-caption">{stage === "arriving" ? "丞相入殿——" : stage === "presented" ? "臣谨呈奏，请陛下御览" : "臣领旨，叩谢圣恩"}</div>
    <div className="chancellor-figure" aria-label="丞相进殿呈奏">
      <svg viewBox="0 0 100 180" role="img" aria-hidden="true">
        <path className="official-hat" d="M31 35h38l-4-13H35zM5 26h90v10H5z" />
        <circle cx="50" cy="49" r="14" />
        <path className="official-robe" d="M35 63h30l13 23-10 13-7-11 9 72H30l9-72-8 11-10-13z" />
        <path className="official-sleeves" d="M29 73 5 112l23 10 20-31 4 3 20 28 23-10-24-39-21 12z" />
        <rect className="held-memorial" x="34" y="100" width="32" height="12" rx="2" />
      </svg>
    </div>
    <div className="flying-memorial" aria-hidden="true"><span /></div>
  </div>;
}
