export function BrandMark({
  className = "brand-icon",
}: {
  className?: string;
}) {
  return (
    <img
      className={className}
      src="/icons/clms-icon.svg"
      width="40"
      height="40"
      alt=""
      draggable={false}
    />
  );
}

export function Brand() {
  return (
    <>
      <BrandMark />
      <span className="brand-wordmark">
        CLMS<small>作文档案馆</small>
      </span>
    </>
  );
}
