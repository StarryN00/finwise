/**
 * FinWise ECharts Theme — Warm Cream + Terracotta
 * Built on the design system CSS variables
 * Apply via: echarts.registerTheme('finwise', finwiseTheme)
 */

export const finwiseTheme = {
  color: [
    '#cc785c',  // terracotta — primary
    '#3d6b4a',  // success green
    '#a86a1f',  // warning orange
    '#5a7a9a',  // info blue
    '#9c7ab5',  // purple
    '#c0392b',  // danger
    '#dda490',  // light terracotta
    '#6a9b7a',  // light green
    '#d4a055',  // gold
    '#7a9bb5'   // light blue
  ],

  backgroundColor: 'transparent',

  textStyle: {
    fontFamily: '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", -apple-system, sans-serif',
    color: '#5c5645'
  },

  title: {
    textStyle: {
      color: '#29261b',
      fontWeight: 700,
      fontSize: 16
    },
    subtextStyle: {
      color: '#9c9786',
      fontSize: 12
    }
  },

  line: {
    itemStyle: { borderWidth: 2 },
    lineStyle: { width: 2.5 },
    symbolSize: 6,
    symbol: 'circle',
    smooth: false
  },

  bar: {
    itemStyle: {
      borderRadius: [4, 4, 0, 0]
    }
  },

  pie: {
    itemStyle: {
      borderWidth: 2,
      borderColor: '#faf9f6'
    }
  },

  radar: {
    axisName: {
      color: '#5c5645',
      fontSize: 12,
      fontWeight: 600
    },
    splitNumber: 4,
    splitLine: {
      lineStyle: { color: '#e8e4da' }
    },
    splitArea: {
      areaStyle: { color: ['#faf9f6', '#f5f3ee'] }
    },
    axisLine: {
      lineStyle: { color: '#e8e4da' }
    }
  },

  gauge: {
    axisLine: {
      lineStyle: {
        color: [
          [0.3, '#3d6b4a'],
          [0.7, '#cc785c'],
          [1, '#c0392b']
        ]
      }
    },
    axisTick: { distance: -20 },
    splitLine: { distance: -20 }
  },

  tooltip: {
    backgroundColor: '#ffffff',
    borderColor: '#e8e4da',
    borderWidth: 1,
    borderRadius: 8,
    padding: [10, 14],
    textStyle: { color: '#29261b', fontSize: 13 },
    extraCssText: 'box-shadow: 0 4px 12px rgba(41, 38, 27, 0.08);'
  },

  legend: {
    textStyle: { color: '#5c5645', fontSize: 12 },
    pageTextStyle: { color: '#9c9786' }
  },

  categoryAxis: {
    axisLine: { lineStyle: { color: '#e8e4da' } },
    axisTick: { lineStyle: { color: '#e8e4da' } },
    axisLabel: { color: '#9c9786', fontSize: 12 },
    splitLine: { lineStyle: { color: '#f0ece0' } }
  },

  valueAxis: {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: '#9c9786', fontSize: 12 },
    splitLine: { lineStyle: { color: '#f0ece0', type: 'dashed' } }
  }
}

export default finwiseTheme