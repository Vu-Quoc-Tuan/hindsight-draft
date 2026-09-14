import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  generatePartitionTicketReport,
  downloadPartitionDiffJson,
  copyToClipboard,
} from './partitionExport'

describe('partitionExport', () => {
  it('generates formatted ticket report correctly', () => {
    const report = generatePartitionTicketReport({
      chainId: 'CHAIN-VN-001',
      operation: 'MANUAL_SPLIT',
      operatorId: 'expert_reviewer_1',
      reasonCode: 'MANUAL_TOPOLOGY_SPLIT',
      notes: 'Separating BTS-01 from optical transport ring',
      partitionDelta: {
        after: [
          ['CHAIN-VN-001', ['alarm-001']],
          ['CHAIN-VN-001::partition_custom', ['alarm-002', 'alarm-003']],
        ],
      },
      alarmMap: {
        'alarm-001': { device_code: 'SW-CORE-01', alarm_name: 'LINK_DOWN', role: 'PRIMARY' },
        'alarm-002': { device_code: 'BTS-01', alarm_name: 'ETH_LOS', role: 'WEAK' },
      },
    })

    expect(report).toContain('BÁO CÁO PHÂN HOẠCH SỰ CỐ NOCPRO')
    expect(report).toContain('Mã chuỗi sự cố (Incident Chain) : CHAIN-VN-001')
    expect(report).toContain('Nghiệp vụ điều chỉnh (Operation) : MANUAL_SPLIT')
    expect(report).toContain('Kỹ sư thực hiện (Operator)      : expert_reviewer_1')
    expect(report).toContain('Separating BTS-01 from optical transport ring')
    expect(report).toContain('[Phân vùng 1]: CHAIN-VN-001 (1 cảnh báo)')
    expect(report).toContain('alarm-001 [SW-CORE-01]  - LINK_DOWN (PRIMARY)')
    expect(report).toContain('[Phân vùng 2]: CHAIN-VN-001::partition_custom (2 cảnh báo)')
  })

  describe('browser interaction with mock DOM', () => {
    let mockElement: any
    let appendSpy: any
    let removeSpy: any
    let writeTextSpy: any

    beforeEach(() => {
      mockElement = {
        href: '',
        download: '',
        click: vi.fn(),
        style: {},
        value: '',
        focus: vi.fn(),
        select: vi.fn(),
      }
      appendSpy = vi.fn()
      removeSpy = vi.fn()
      writeTextSpy = vi.fn().mockResolvedValue(undefined)

      vi.stubGlobal('document', {
        createElement: vi.fn().mockReturnValue(mockElement),
        body: {
          appendChild: appendSpy,
          removeChild: removeSpy,
        },
        execCommand: vi.fn().mockReturnValue(true),
      })
      vi.stubGlobal('window', {
        isSecureContext: true,
        URL: {
          createObjectURL: vi.fn().mockReturnValue('blob:http://localhost/test'),
          revokeObjectURL: vi.fn(),
        },
      })
      vi.stubGlobal('navigator', {
        clipboard: {
          writeText: writeTextSpy,
        },
      })
    })

    afterEach(() => {
      vi.unstubAllGlobals()
    })

    it('downloads partition diff json using browser blob', () => {
      downloadPartitionDiffJson({
        chainId: 'CHAIN-VN-001',
        operation: 'MANUAL_MERGE',
        operatorId: 'operator_test',
        partitionDelta: { after: [['CHAIN-VN-001', ['a1', 'a2']]] },
      })

      expect(appendSpy).toHaveBeenCalled()
      expect(removeSpy).toHaveBeenCalled()
      expect(mockElement.click).toHaveBeenCalled()
    })

    it('copies to clipboard using navigator.clipboard', async () => {
      const success = await copyToClipboard('test clipboard text')
      expect(success).toBe(true)
      expect(writeTextSpy).toHaveBeenCalledWith('test clipboard text')
    })
  })
})
