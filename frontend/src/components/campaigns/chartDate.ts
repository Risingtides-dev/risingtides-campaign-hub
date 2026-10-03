export const formatChartDateLabel = (value: unknown) =>
  new Date(Number(value)).toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })

export const localTickDate = (value: number) => {
  const d = new Date(value)
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

export const chartAxisProps = { tickFormatter: localTickDate }
export const chartTooltipProps = { labelFormatter: formatChartDateLabel }
