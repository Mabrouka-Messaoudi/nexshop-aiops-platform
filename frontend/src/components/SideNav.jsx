const NAV_ITEMS = [
  { id: "cockpit", label: "Cockpit", hint: "Rejeu live" },
  { id: "live", label: "Cluster réel", hint: "Flux live" },
  { id: "m4demo", label: "M4 — Seuil dynamique", hint: "Scénario dédié" },
  { id: "test", label: "Tester un modèle", hint: "Appel direct" },
  { id: "explainability", label: "Explicabilité", hint: "Pourquoi" },
  { id: "performance", label: "Performance", hint: "Preuves" },
];

export default function SideNav({ active, onChange }) {
  return (
    <nav className="sidenav">
      <div className="sidenav__mark">
        <span className="sidenav__mark-glyph">N</span>
      </div>
      <div className="sidenav__items">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`sidenav__item ${active === item.id ? "is-active" : ""}`}
            onClick={() => onChange(item.id)}
          >
            <span className="sidenav__item-label">{item.label}</span>
            <span className="sidenav__item-hint">{item.hint}</span>
          </button>
        ))}
      </div>
    </nav>
  );
}
