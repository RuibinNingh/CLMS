import { useEffect, useId, useRef, type ReactNode } from "react";

export type ReadingPanel = "paper" | "evaluation";

export function ReadingLayout({
  paper,
  evaluation,
  panel,
  onPanel,
  location,
  locationKey,
  className = "",
  paperLabel = "原稿",
  evaluationLabel = "评价",
}: {
  paper: ReactNode;
  evaluation: ReactNode;
  panel: ReadingPanel;
  onPanel: (panel: ReadingPanel) => void;
  className?: string;
  location?: string;
  locationKey?: number;
  paperLabel?: string;
  evaluationLabel?: string;
}) {
  const id = useId();
  const paperRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (location && panel === "paper") {
      paperRef.current?.scrollIntoView({ block: "start" });
      paperRef.current?.focus({ preventScroll: true });
    }
  }, [location, locationKey, panel]);
  return (
    <>
      <div className="reading-switch" role="group" aria-label="阅读面板">
        {(
          [
            ["paper", paperLabel],
            ["evaluation", evaluationLabel],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            aria-pressed={panel === value}
            aria-controls={`${id}-${value}`}
            onClick={() => onPanel(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className={`reading-layout ${className}`} data-panel={panel}>
        <div
          className="reading-paper"
          id={`${id}-paper`}
          ref={paperRef}
          tabIndex={-1}
          role="group"
          aria-label="原稿阅读区"
        >
          {paper}
        </div>
        <div className="reading-evaluation" id={`${id}-evaluation`}>
          {evaluation}
        </div>
      </div>
    </>
  );
}
