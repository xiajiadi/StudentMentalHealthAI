import { describe, expect, it } from 'vitest'
import { parseSchoolAccountCsv } from '@/utils/school-account-csv'

describe('学校合成账号 CSV 解析器', () => {
  it('接受 BOM、CRLF、引号、逗号和双引号转义', () => {
    const csv = '\uFEFFlogin_name,display_name,role\r\nSYNTHETIC_A,"学生, 一号",student\r\nSYNTHETIC_B,"教师 ""乙""",teacher\r\n'
    expect(parseSchoolAccountCsv(csv)).toEqual({
      ok: true,
      rows: [
        { row_no: 1, login_name: 'SYNTHETIC_A', display_name: '学生, 一号', role: 'student' },
        { row_no: 2, login_name: 'SYNTHETIC_B', display_name: '教师 "乙"', role: 'teacher' },
      ],
    })
  })

  it('严格拒绝密码列、额外列、不成对引号和非法 UTF-8', () => {
    expect(parseSchoolAccountCsv('login_name,display_name,password\nSYNTHETIC_A,学生,pw')).toMatchObject({ ok: false, code: 'CSV_INVALID_HEADER' })
    expect(parseSchoolAccountCsv('login_name,display_name,role,extra\nSYNTHETIC_A,学生,student,x')).toMatchObject({ ok: false, code: 'CSV_INVALID_HEADER' })
    expect(parseSchoolAccountCsv('login_name,display_name,role\nSYNTHETIC_A,"学生,student')).toMatchObject({ ok: false, code: 'CSV_MALFORMED' })
    expect(parseSchoolAccountCsv(new Uint8Array([0xff, 0xfe]))).toMatchObject({ ok: false, code: 'CSV_INVALID_UTF8' })
  })

  it('检查大小、行数、空名称、登录名、重复项和精确角色', () => {
    expect(parseSchoolAccountCsv(new Uint8Array(500 * 1024 + 1))).toMatchObject({ ok: false, code: 'CSV_TOO_LARGE' })
    const tooManyRows = ['login_name,display_name,role', ...Array.from({ length: 101 }, (_, index) => `SYNTHETIC_${index},名${index},student`)].join('\n')
    expect(parseSchoolAccountCsv(tooManyRows)).toMatchObject({ ok: false, code: 'CSV_TOO_MANY_ROWS' })
    expect(parseSchoolAccountCsv('login_name,display_name,role\nSYNTHETIC_A,  ,student')).toMatchObject({ ok: false, code: 'DISPLAY_NAME_INVALID' })
    expect(parseSchoolAccountCsv('login_name,display_name,role\nBAD_LOGIN,学生,student')).toMatchObject({ ok: false, code: 'LOGIN_NAME_INVALID' })
    expect(parseSchoolAccountCsv('login_name,display_name,role\nSYNTHETIC_A,甲,student\nSYNTHETIC_a,乙,teacher')).toMatchObject({ ok: false, code: 'LOGIN_NAME_DUPLICATE' })
    expect(parseSchoolAccountCsv('login_name,display_name,role\nSYNTHETIC_A,甲,Student')).toMatchObject({ ok: false, code: 'ROLE_INVALID' })
  })
})
