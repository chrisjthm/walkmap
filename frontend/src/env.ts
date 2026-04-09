const trimTrailingSlash = (value: string) =>
  value.endsWith("/") ? value.slice(0, -1) : value;

export const getApiBase = () => {
  const rawBase = import.meta.env.VITE_API_BASE_URL;
  if (!rawBase) {
    return "";
  }
  return trimTrailingSlash(rawBase);
};

export const getMapStyleUrl = () =>
  import.meta.env.VITE_MAP_STYLE_URL ?? "https://tiles.openfreemap.org/styles/liberty";
