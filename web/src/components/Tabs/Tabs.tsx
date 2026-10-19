import { useId, type KeyboardEvent, type ReactNode } from "react";
import styles from "./Tabs.module.css";

export type TabDef = {
  id: string;
  label: string;
  panel: ReactNode;
};

export function Tabs({
  tabs,
  activeId,
  onChange,
  label,
}: {
  label: string;
  tabs: TabDef[];
  activeId: string;
  onChange: (id: string) => void;
}) {
  const baseId = useId();
  const activeIndex = Math.max(
    0,
    tabs.findIndex((t) => t.id === activeId),
  );
  const active = tabs[activeIndex] ?? tabs[0];

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next = index;
    if (e.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    else return;
    e.preventDefault();
    onChange(tabs[next]!.id);
    document.getElementById(`${baseId}-tab-${tabs[next]!.id}`)?.focus();
  };

  return (
    <div className={styles.root}>
      <div role="tablist" aria-label={label} className={styles.tablist}>
        {tabs.map((tab, i) => {
          const selected = tab.id === active?.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`${baseId}-tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`${baseId}-panel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              className={styles.tab}
              onClick={() => onChange(tab.id)}
              onKeyDown={(e) => onKeyDown(e, i)}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      {active && (
        <div
          role="tabpanel"
          id={`${baseId}-panel-${active.id}`}
          aria-labelledby={`${baseId}-tab-${active.id}`}
          className={styles.panel}
          tabIndex={0}
        >
          {active.panel}
        </div>
      )}
    </div>
  );
}
