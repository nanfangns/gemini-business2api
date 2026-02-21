<template>
  <div class="space-y-6">
    <!-- 统计卡片：纸张质感 -->
    <section class="grid grid-cols-2 gap-4 md:grid-cols-4">
      <div
        v-for="stat in stats"
        :key="stat.label"
        class="ios-glass ios-pressable group relative overflow-hidden rounded-2xl p-6"
      >
        <div class="absolute top-0 left-0 h-1 w-0 bg-primary transition-all duration-[var(--motion-medium)] ease-[var(--ease-ios)] group-hover:w-full"></div>
        <p class="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">{{ stat.label }}</p>
        <p class="mt-4 text-3xl font-black tracking-tight text-foreground">{{ stat.value }}</p>
        <p class="mt-2 text-[10px] font-medium text-muted-foreground line-clamp-1">{{ stat.caption }}</p>
      </div>
    </section>

    <!-- 图表区域：布局优化 -->
    <section class="flex w-full flex-col gap-6 lg:flex-row">
      <div class="ios-glass w-full flex-1 min-w-0 rounded-2xl p-6">
        <div class="flex items-center justify-between border-b border-border/40 pb-4">
          <p class="text-sm font-bold tracking-tight text-foreground">调用趋势 (近12小时)</p>
          <div class="flex items-center gap-2">
            <span class="h-2 w-2 rounded-full bg-primary"></span>
            <span class="text-[10px] font-bold text-muted-foreground uppercase">Trend Analysis</span>
          </div>
        </div>
        <div ref="trendChartRef" class="mt-6 h-64 w-full lg:h-72"></div>

        <div class="mt-8 border-t border-border/40 pt-6">
          <p class="text-sm font-bold tracking-tight text-foreground">模型调用分布</p>
          <div ref="modelChartRef" class="mt-6 h-80 w-full lg:h-64"></div>
        </div>
      </div>

      <div class="ios-glass w-full shrink-0 rounded-2xl p-6 lg:w-80">
        <p class="border-b border-border/40 pb-4 text-sm font-bold tracking-tight text-foreground">账号健康程度</p>
        <div class="mt-6 space-y-5">
          <div v-for="item in accountBreakdown" :key="item.label" class="space-y-2">
            <div class="flex items-center justify-between">
              <span class="flex items-center gap-2 text-[11px] font-bold text-muted-foreground uppercase">
                {{ item.label }}
                <HelpTip v-if="item.tooltip" :text="item.tooltip" />
              </span>
              <span class="text-xs font-black text-foreground">{{ item.value }}</span>
            </div>
            <div class="h-1.5 w-full overflow-hidden rounded-full bg-muted/50">
              <div class="h-full rounded-full transition-all duration-[var(--motion-slow)] ease-[var(--ease-ios)]" :class="item.barClass" :style="{ width: item.percent + '%' }"></div>
            </div>
          </div>
        </div>
        <div class="mt-8 rounded-2xl border border-primary/15 bg-primary/10 p-4">
          <p class="text-[10px] font-bold leading-relaxed text-primary/80 uppercase tracking-wider">
            Smart Advice: 建议及时处理异常账号，确保持续可用性。
          </p>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { statsApi } from '@/api'
import HelpTip from '@/components/ui/HelpTip.vue'

type ChartInstance = {
  setOption: (option: unknown) => void
  resize: () => void
  dispose: () => void
}

const stats = ref([
  { label: '账号总数', value: '0', caption: '账号池中已加载的总数量。' },
  { label: '活跃账号', value: '0', caption: '未过期、未禁用、未限流且可用。' },
  { label: '失败账号', value: '0', caption: '自动禁用或已过期，需要处理。' },
  { label: '限流账号', value: '0', caption: '触发 429 限流，冷却中。' },
])

const trendData = ref<number[]>([])
const trendFailureData = ref<number[]>([])
const trendSuccessData = ref<number[]>([])
const trendLabels = ref<string[]>([])
const trendModelRequests = ref<Record<string, number[]>>({})

const trendChartRef = ref<HTMLDivElement | null>(null)
const modelChartRef = ref<HTMLDivElement | null>(null)
let trendChart: ChartInstance | null = null
let modelChart: ChartInstance | null = null

const accountBreakdown = computed(() => {
  const total = Math.max(Number(stats.value[0].value), 1)
  const active = Number(stats.value[1].value)
  const failed = Number(stats.value[2].value)
  const rateLimited = Number(stats.value[3].value)
  const available = Math.max(total - active - failed - rateLimited, 0)

  return [
    {
      label: '活跃',
      value: active,
      percent: Math.round((active / total) * 100),
      barClass: 'bg-primary shadow-[0_0_10px_hsla(var(--primary),0.35)]',
    },
    {
      label: '失败',
      value: failed,
      percent: Math.round((failed / total) * 100),
      barClass: 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.3)]',
    },
    {
      label: '限流',
      value: rateLimited,
      percent: Math.round((rateLimited / total) * 100),
      barClass: 'bg-amber-400',
    },
    {
      label: '空闲',
      tooltip: '未限流、未失败、未激活使用中的账号（主要是手动禁用）。',
      value: available,
      percent: Math.round((available / total) * 100),
      barClass: 'bg-muted',
    },
  ]
})

onMounted(async () => {
  await loadOverview()
  initTrendChart()
  initModelChart()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  if (trendChart) {
    trendChart.dispose()
    trendChart = null
  }
  if (modelChart) {
    modelChart.dispose()
    modelChart = null
  }
})

function initTrendChart() {
  const echarts = (window as any).echarts as { init: (el: HTMLElement) => ChartInstance } | undefined
  if (!echarts || !trendChartRef.value) return

  trendChart = echarts.init(trendChartRef.value)
  updateTrendChart()
  scheduleTrendResize()
}

function initModelChart() {
  const echarts = (window as any).echarts as { init: (el: HTMLElement) => ChartInstance } | undefined
  if (!echarts || !modelChartRef.value) return

  modelChart = echarts.init(modelChartRef.value)
  updateModelChart()
  scheduleModelResize()
}

function getThemeColor(name: string, fallback: string) {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function updateTrendChart() {
  if (!trendChart) return

  const successColor = getThemeColor('--chart-primary', '#dc2626')
  const failureLineColor = getThemeColor('--chart-danger', '#f43f5e')
  const axisLineColor = getThemeColor('--chart-grid', 'rgba(148, 103, 103, 0.18)')
  const axisLabelColor = getThemeColor('--chart-label', 'rgba(103, 72, 72, 0.72)')

  trendChart.setOption({
    animationDuration: 320,
    animationDurationUpdate: 240,
    animationEasing: 'cubicOut',
    animationEasingUpdate: 'cubicOut',
    tooltip: { trigger: 'axis' },
    legend: {
      data: ['成功(总请求)', '失败/限流'],
      right: 0,
      top: 0,
      textStyle: { color: axisLabelColor, fontSize: 11 },
    },
    grid: { left: 24, right: 16, top: 44, bottom: 24, containLabel: true },
    xAxis: {
      type: 'category',
      data: trendLabels.value,
      boundaryGap: false,
      axisLine: { lineStyle: { color: axisLineColor } },
      axisTick: { show: false },
      axisLabel: { color: axisLabelColor, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: axisLabelColor, fontSize: 10 },
      splitLine: { lineStyle: { color: axisLineColor } },
    },
    series: [
      {
        name: '成功(总请求)',
        type: 'line',
        data: trendSuccessData.value,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.25 },
        itemStyle: { color: successColor },
        emphasis: { disabled: true },
        z: 1,
      },
      {
        name: '失败/限流',
        type: 'line',
        data: trendFailureData.value,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.4 },
        itemStyle: { color: failureLineColor },
        emphasis: { disabled: true },
        z: 2,
      },
    ],
  })
  scheduleTrendResize()
}

function updateModelChart() {
  if (!modelChart) return

  const modelTotals = Object.entries(trendModelRequests.value)
    .map(([model, data]) => ({
      name: model,
      value: data.reduce((sum, item) => sum + item, 0),
      itemStyle: { color: getModelColor(model), borderRadius: 8 },
    }))
    .filter(item => item.value > 0)

  const isMobile = window.innerWidth < 768
  const axisLabelColor = getThemeColor('--chart-label', 'rgba(103, 72, 72, 0.72)')
  const axisLineColor = getThemeColor('--chart-grid', 'rgba(148, 103, 103, 0.18)')
  const legendConfig = isMobile
    ? {
        data: modelTotals.map(item => item.name),
        left: 'center',
        bottom: 0,
        orient: 'horizontal' as const,
        textStyle: { color: axisLabelColor, fontSize: 11 },
      }
    : {
        data: modelTotals.map(item => item.name),
        left: 0,
        top: 'center',
        orient: 'vertical' as const,
        textStyle: { color: axisLabelColor, fontSize: 11 },
      }

  const pieCenter = isMobile ? ['50%', '38%'] : ['66%', '50%']
  const pieRadius = isMobile ? ['40%', '62%'] : ['52%', '78%']

  modelChart.setOption({
    animation: true,
    animationDuration: 600,
    animationEasing: 'cubicOut',
    animationDurationUpdate: 300,
    animationEasingUpdate: 'cubicOut',
    tooltip: {
      trigger: 'item',
      formatter: (params: { name: string; value: number; percent: number }) =>
        `${params.name}: ${params.value} 次 (${params.percent}%)`,
    },
    legend: {
      ...legendConfig,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: axisLabelColor, fontSize: 10, fontWeight: 'bold' },
    },
    series: [
      {
        type: 'pie',
        radius: pieRadius,
        center: pieCenter,
        startAngle: 90,
        animationType: 'scale',
        animationEasing: 'cubicOut',
        avoidLabelOverlap: true,
        label: { show: true, formatter: '{b}', fontSize: 11, color: axisLabelColor },
        labelLine: { length: 15, length2: 12, lineStyle: { color: axisLineColor } },
        itemStyle: { borderWidth: 4, borderColor: '#fff' },
        data: modelTotals,
      },
    ],
  })
  scheduleModelResize()
}

function handleResize() {
  if (trendChart) {
    trendChart.resize()
  }
  if (modelChart) {
    // 重新渲染图表以应用响应式布局
    updateModelChart()
  }
}

async function loadOverview() {
  try {
    const overview = await statsApi.overview()
    stats.value[0].value = (overview.total_accounts ?? 0).toString()
    stats.value[1].value = (overview.active_accounts ?? 0).toString()
    stats.value[2].value = (overview.failed_accounts ?? 0).toString()
    stats.value[3].value = (overview.rate_limited_accounts ?? 0).toString()

    const trend = overview.trend || { labels: [], total_requests: [], failed_requests: [], rate_limited_requests: [] }
    trendLabels.value = trend.labels || []
    trendData.value = trend.total_requests || []
    const failed = trend.failed_requests || []
    const limited = trend.rate_limited_requests || []
    const failureSeries = trendData.value.map((_, idx) => (failed[idx] || 0) + (limited[idx] || 0))
    trendFailureData.value = failureSeries
    trendSuccessData.value = trendData.value.map(item => Math.max(item, 0))
    trendModelRequests.value = trend.model_requests || {}

    updateTrendChart()
    updateModelChart()
  } catch (error) {
    console.error('Failed to load overview:', error)
  }
}

function scheduleTrendResize() {
  if (!trendChart) return
  requestAnimationFrame(() => {
    trendChart?.resize()
  })
}

function scheduleModelResize() {
  if (!modelChart) return
  requestAnimationFrame(() => {
    modelChart?.resize()
  })
}

function getModelColor(model: string) {
  const modelColors: Record<string, string> = {
    'gemini-3-pro-preview': '#dc2626',
    'gemini-3.1-pro-preview': '#f59e0b',
    'gemini-2.5-pro': '#f97316',
    'gemini-2.5-flash': '#fb7185',
    'gemini-3-flash-preview': '#f43f5e',
    'gemini-auto': '#a16207',
  }
  return modelColors[model] || '#a16207'
}
</script>
