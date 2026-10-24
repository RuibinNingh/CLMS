import { useEffect } from "react";
import { api } from "../../shared/api";
import { useLoad } from "../../shared/hooks";
import type { Paged, Review } from "../../shared/types";

export const refreshReviewCount = () =>
  window.dispatchEvent(new Event("clms-reviews-changed"));
export function PendingReviewBadge({ route }: { route: string }) {
  const count = useLoad(
    () => api<Paged<Review>>("/reviews?status=pending&limit=1"),
    [route],
  );
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") count.reload();
    };
    const timer = setInterval(refresh, 30000);
    window.addEventListener("focus", refresh);
    window.addEventListener("clms-reviews-changed", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", refresh);
      window.removeEventListener("clms-reviews-changed", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [count.reload]);
  const total = count.data?.total;
  return !count.error && total != null && total > 0 ? (
    <span
      className="review-nav-badge"
      role="status"
      aria-label={`${total} 项待审核`}
      title={`${total} 项提案等待你确认`}
    >
      {total > 99 ? "99+" : total}
    </span>
  ) : null;
}
