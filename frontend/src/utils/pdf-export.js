/**
 * FinWise PDF Export Utility
 * Generates localized A4 PDFs using html2canvas + jsPDF
 * Background: warm cream (#faf9f6), accent: terracotta (#cc785c)
 */

import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'

// Design tokens shared for PDF generation (background, accent, text colors)

/**
 * Export a DOM element as a localized FinWise PDF
 * @param {HTMLElement} element - DOM element to capture
 * @param {string} filename - Output filename without extension
 * @param {object} options - { title, companyName, date }
 */
export async function exportToPdf(element, filename = 'finwise-report', options = {}) {
  const { title = '财务报告', companyName = '', date = new Date().toLocaleDateString('zh-CN') } = options

  // Capture the element
  const canvas = await html2canvas(element, {
    scale: 2,
    useCORS: true,
    backgroundColor: '#faf9f6',
    logging: false
  })

  const imgData = canvas.toDataURL('image/png')
  const pdf = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })

  const pw = pdf.internal.pageSize.getWidth()  // 210mm
  const ph = pdf.internal.pageSize.getHeight() // 297mm
  const margin = 15
  const contentW = pw - margin * 2
  const ratio = canvas.height / canvas.width
  const imgH = contentW * ratio

  // Header bar
  pdf.setFillColor(204, 120, 92) // --color-accent
  pdf.rect(0, 0, pw, 18, 'F')

  // Company name in header
  pdf.setTextColor(255, 255, 255)
  pdf.setFontSize(10)
  pdf.setFont('helvetica', 'bold')
  pdf.text('智税管家 FinWise', margin, 11)

  // Report title in header
  pdf.setFontSize(10)
  pdf.setFont('helvetica', 'normal')
  const titleText = title
  const titleW = pdf.getTextWidth(titleText)
  pdf.text(titleText, pw - margin - titleW, 11)

  // Report info bar
  pdf.setFillColor(245, 243, 238) // --color-bg-alt
  pdf.rect(0, 18, pw, 10, 'F')
  pdf.setTextColor(156, 151, 134) // --color-text-muted
  pdf.setFontSize(8)
  pdf.setFont('helvetica', 'normal')
  pdf.text(`企业：${companyName || '—'}`, margin, 24.5)
  const dateText = `生成日期：${date}`
  const dateW = pdf.getTextWidth(dateText)
  pdf.text(dateText, pw - margin - dateW, 24.5)

  const contentTop = 30
  let y = contentTop

  // Add content image(s)
  while (y < ph - 20) {
    const remaining = ph - 20 - y
    const sliceH = Math.min(imgH, remaining)
    const sliceRatio = sliceH / imgH

    if (sliceRatio < 0.05) break

    pdf.addImage(
      imgData, 'PNG',
      margin, y,
      contentW, imgH,
      undefined, 'FAST',
      0
    )
    y += sliceH

    if (y < ph - 20 && y > contentTop) {
      pdf.addPage()
      // Mini header on continued page
      pdf.setFillColor(204, 120, 92)
      pdf.rect(0, 0, pw, 10, 'F')
      pdf.setTextColor(255, 255, 255)
      pdf.setFontSize(8)
      pdf.setFont('helvetica', 'bold')
      pdf.text('智税管家 FinWise', margin, 6.5)
      const contText = `（续）${title}`
      const contW = pdf.getTextWidth(contText)
      pdf.text(contText, pw - margin - contW, 6.5)
    }
  }

  // Footer on last page
  const pageCount = pdf.internal.getNumberOfPages()
  for (let i = 1; i <= pageCount; i++) {
    pdf.setPage(i)
    pdf.setFillColor(240, 236, 224) // --color-surface
    pdf.rect(0, ph - 12, pw, 12, 'F')
    pdf.setTextColor(156, 151, 134)
    pdf.setFontSize(7)
    pdf.setFont('helvetica', 'normal')
    pdf.text(`第 ${i} / ${pageCount} 页`, pw / 2, ph - 4.5, { align: 'center' })
    const disclaimer = '本报告由智税管家系统自动生成，仅供运营参考，不作为法律依据'
    const discW = pdf.getTextWidth(disclaimer)
    pdf.text(disclaimer, pw - margin - discW, ph - 4.5)
  }

  pdf.save(`${filename}.pdf`)
  return { pageCount }
}

export default exportToPdf
