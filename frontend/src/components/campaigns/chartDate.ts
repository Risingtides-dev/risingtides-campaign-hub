export const formatChartDateLabel = (value: unknown) =>
  new Date(Number(value)).toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
