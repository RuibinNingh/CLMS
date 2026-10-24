export function applyTheme(choice: string) {
  const theme =
    choice === "system"
      ? matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : choice;
  document.documentElement.dataset.theme = theme;
  const surface = getComputedStyle(document.documentElement)
    .getPropertyValue("--surface-0")
    .trim();
  if (surface)
    document
      .querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')
      .forEach((meta) => {
        meta.content = surface;
      });
}
export function saveTheme(choice: string) {
  localStorage.setItem("clms-theme", choice);
  applyTheme(choice);
}
