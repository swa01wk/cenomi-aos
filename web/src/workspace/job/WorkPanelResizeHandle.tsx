import styles from "./WorkPanelResizeHandle.module.css";

type WorkPanelResizeHandleProps = {
  onResizeStart: (clientX: number) => void;
  onReset: () => void;
  /** Hide on viewports where the my-jobs layout stacks (non person-chat). */
  jobLayout?: boolean;
};

/** Drag to widen or narrow the work panel; double-click resets default width. */
export function WorkPanelResizeHandle({ onResizeStart, onReset, jobLayout }: WorkPanelResizeHandleProps) {
  return (
    <div
      className={[styles.handle, jobLayout ? styles.handleJobOnly : ""].filter(Boolean).join(" ")}
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize work panel"
      title="Drag to resize. Double-click to reset."
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        onResizeStart(e.clientX);
      }}
      onDoubleClick={(e) => {
        e.preventDefault();
        onReset();
      }}
    />
  );
}
