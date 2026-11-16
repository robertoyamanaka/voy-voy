// Product chips for the apps VoyVoy calls through. The Google Meet mark is the Simple Icons
// silhouette (CC0) split into its parts and colored like the real logo; Zoom is its app icon shape.

function MeetIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#EA4335" d="M5.53 2.13 0 7.75h5.53z" />
      <path fill="#FFBA00" d="M5.928 2.13v5.62h7.608v3.65l5.47-4.45c-.014-1.22.031-2.25-.025-3.46-.148-1.09-1.287-1.47-2.236-1.36z" />
      <path fill="#00AC47" d="M23.1 4.32c-.802.295-1.358.995-2.047 1.49-2.506 2.05-4.982 4.12-7.468 6.19 3.025 2.59 6.04 5.18 9.065 7.76 1.218.671 1.428-.814 1.328-1.64v-13a.828.828 0 0 0-.877-.825z" />
      <path fill="#2684FC" d="M.038 8.15v7.7h5.53v-7.7z" />
      <path fill="#00832D" d="M13.615 16.25H6.008v5.62c3.864-.006 7.737.011 11.58-.009 1.02-.07 1.618-1.12 1.468-2.07v-2.51l-5.47-4.68v3.65z" />
      <path fill="#0066DA" d="M.038 16.25c.02 1.44-.041 2.88.033 4.31.162.948 1.158 1.43 2.047 1.31h3.464v-5.62z" />
    </svg>
  );
}

function ZoomIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <rect width="24" height="24" rx="6" fill="#0B5CFF" />
      <rect x="4.5" y="8" width="10.5" height="8" rx="2" fill="#fff" />
      <path d="M15.8 11.1 19.5 8.6v6.8l-3.7-2.5z" fill="#fff" />
    </svg>
  );
}

export function ProductChip({ product, soon = false }: { product: "meet" | "zoom"; soon?: boolean }) {
  return (
    <span className={`chip chip-${product}`}>
      {product === "meet" ? <MeetIcon /> : <ZoomIcon />}
      {product === "meet" ? "Google Meet" : "Zoom"}
      {soon && <small>soon</small>}
    </span>
  );
}
