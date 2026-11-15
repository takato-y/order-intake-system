Attribute VB_Name = "MonthlyReport"
'==============================================================
' MonthlyReport.bas : 月次集計 CSV を取り込み、月次受注帳票を作成する
'   入力: batch/monthly_report.py が出力する monthly_orders_YYYY-MM.csv（BOM 付き UTF-8）
'   出力: 「テンプレート」シートを複製した「帳票_YYYY-MM」シート
'   使い方: マクロ CreateMonthlyReport を実行し、CSV を選ぶ
'==============================================================
Option Explicit

Private Const TEMPLATE_SHEET As String = "テンプレート"
Private Const HEADER_ROW As Long = 4
Private Const EXPECTED_HEADER As String = "集計月,顧客名,商品,件数,数量合計"

' 利用者が実行する入口。ファイル選択だけを行い、処理本体は BuildMonthlyReport に任せる
Public Sub CreateMonthlyReport()
    Dim path As Variant
    path = Application.GetOpenFilename("CSV ファイル (*.csv),*.csv", , "月次集計 CSV を選択")
    If VarType(path) = vbBoolean Then Exit Sub   ' キャンセル
    On Error GoTo Failed
    MsgBox "「" & BuildMonthlyReport(CStr(path)) & "」を作成しました。", vbInformation
    Exit Sub
Failed:
    MsgBox "帳票を作成できませんでした。" & vbCrLf & Err.Description, vbExclamation
End Sub

' CSV を読み込み、帳票シートを作成してシート名を返す
Public Function BuildMonthlyReport(ByVal csvPath As String) As String
    Dim lines As Variant, f As Variant, ws As Worksheet
    Dim i As Long, r As Long, reportMonth As String, prevCustomer As String
    Dim subCount As Long, subQty As Long, totalCount As Long, totalQty As Long

    lines = ReadUtf8Lines(csvPath)
    ' 列の並びが変わった CSV を黙って取り込むと数字の列がずれるため、見出しで照合して止める
    If lines(0) <> EXPECTED_HEADER Then
        Err.Raise vbObjectError + 1, , "CSV の見出しが想定と異なります: " & lines(0)
    End If
    reportMonth = MonthFromFileName(csvPath)

    Set ws = CopyTemplate("帳票_" & reportMonth)
    ws.Range("A1").Value = "月次受注帳票（" & reportMonth & "）"
    ws.Range("D2").Value = "作成日時 " & Format(Now, "yyyy/mm/dd hh:nn")
    r = HEADER_ROW + 1

    For i = 1 To UBound(lines)
        If Len(lines(i)) > 0 Then
            f = ParseCsvLine(lines(i))
            If UBound(f) <> 4 Then
                Err.Raise vbObjectError + 2, , "列数が正しくありません（" & (i + 1) & " 行目）"
            End If
            ' CSV は顧客名順に並んでいる前提で、顧客が変わったところに小計を入れる
            If prevCustomer <> "" And f(1) <> prevCustomer Then
                WriteTotalRow ws, r, prevCustomer & " 小計", subCount, subQty, False
                r = r + 1: subCount = 0: subQty = 0
            End If
            ws.Cells(r, 1).Value = f(1)
            ws.Cells(r, 2).Value = f(2)
            ws.Cells(r, 3).Value = CLng(f(3))
            ws.Cells(r, 4).Value = CLng(f(4))
            subCount = subCount + CLng(f(3)): subQty = subQty + CLng(f(4))
            totalCount = totalCount + CLng(f(3)): totalQty = totalQty + CLng(f(4))
            prevCustomer = f(1)
            r = r + 1
        End If
    Next i
    If prevCustomer <> "" Then
        WriteTotalRow ws, r, prevCustomer & " 小計", subCount, subQty, False
        r = r + 1
    End If
    WriteTotalRow ws, r, "総合計", totalCount, totalQty, True

    With ws.Range(ws.Cells(HEADER_ROW, 1), ws.Cells(r, 4))
        .Borders.LineStyle = xlContinuous
        .Borders.Color = RGB(153, 153, 153)
    End With
    ws.Range(ws.Cells(HEADER_ROW + 1, 3), ws.Cells(r, 4)).NumberFormatLocal = "#,##0"
    ws.Columns("A:B").AutoFit
    SetupPrint ws
    BuildMonthlyReport = ws.Name
End Function

Private Sub WriteTotalRow(ByVal ws As Worksheet, ByVal r As Long, ByVal label As String, _
                          ByVal cnt As Long, ByVal qty As Long, ByVal isGrand As Boolean)
    ws.Cells(r, 1).Value = label
    ws.Cells(r, 3).Value = cnt
    ws.Cells(r, 4).Value = qty
    With ws.Range(ws.Cells(r, 1), ws.Cells(r, 4))
        .Font.Bold = True
        .Interior.Color = IIf(isGrand, RGB(221, 231, 243), RGB(242, 242, 242))
    End With
End Sub

' テンプレートを複製して帳票シートを作る。同じ月を作り直す場合は古いシートを置き換える
Private Function CopyTemplate(ByVal sheetName As String) As Worksheet
    Dim ws As Worksheet
    EnsureTemplate
    Application.DisplayAlerts = False
    On Error Resume Next
    ThisWorkbook.Worksheets(sheetName).Delete
    On Error GoTo 0
    Application.DisplayAlerts = True
    ThisWorkbook.Worksheets(TEMPLATE_SHEET).Copy After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count)
    Set ws = ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count)
    ws.Name = sheetName
    Set CopyTemplate = ws
End Function

' テンプレートがないブックでも動くよう、最低限の様式を作る。
' 既にある場合は利用者が整えた様式（ロゴ・押印欄など）を尊重して触らない
Private Sub EnsureTemplate()
    Dim ws As Worksheet
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets(TEMPLATE_SHEET)
    On Error GoTo 0
    If Not ws Is Nothing Then Exit Sub
    Set ws = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
    ws.Name = TEMPLATE_SHEET
    ws.Range("A1").Value = "月次受注帳票"
    ws.Range("A1").Font.Size = 14
    ws.Range("A1").Font.Bold = True
    ws.Range("A4:D4").Value = Array("顧客名", "商品", "件数", "数量合計")
    With ws.Range("A4:D4")
        .Font.Bold = True
        .Interior.Color = RGB(221, 231, 243)
        .HorizontalAlignment = xlCenter
    End With
    ws.Columns("C:D").ColumnWidth = 12
End Sub

Private Sub SetupPrint(ByVal ws As Worksheet)
    ' プリンタ未設定の PC では PageSetup が実行時エラーになるため、印刷設定の失敗は無視する
    On Error Resume Next
    With ws.PageSetup
        .Orientation = xlPortrait
        .Zoom = False
        .FitToPagesWide = 1
        .FitToPagesTall = False
        .PrintTitleRows = "$" & HEADER_ROW & ":$" & HEADER_ROW
        .CenterFooter = "&P / &N"
    End With
    On Error GoTo 0
End Sub

' 「monthly_orders_2026-11.csv」から「2026-11」を取り出す（データ 0 件の月でも帳票名を決めるため）
Private Function MonthFromFileName(ByVal path As String) As String
    Dim base As String, p As Long
    base = Mid$(path, InStrRev(path, "\") + 1)
    p = InStr(base, "_20")
    If p = 0 Or Len(base) < p + 8 Then Err.Raise vbObjectError + 3, , "ファイル名から集計月を読み取れません: " & base
    MonthFromFileName = Mid$(base, p + 1, 7)
End Function

' BOM 付き UTF-8 を文字化けせずに読むため ADODB.Stream を使う（Open ステートメントは Shift_JIS 前提）
Private Function ReadUtf8Lines(ByVal path As String) As Variant
    Dim st As Object, buf As String
    Set st = CreateObject("ADODB.Stream")
    st.Type = 2          ' adTypeText
    st.Charset = "utf-8"
    st.Open
    st.LoadFromFile path
    buf = st.ReadText(-1)
    st.Close
    If Left$(buf, 1) = ChrW(&HFEFF) Then buf = Mid$(buf, 2)
    buf = Replace(buf, vbCrLf, vbLf)
    If Len(buf) = 0 Then Err.Raise vbObjectError + 4, , "CSV が空です"
    ReadUtf8Lines = Split(buf, vbLf)
End Function

' ダブルクォートで囲んだ項目（カンマ・"" を含む顧客名など）に対応した 1 行分の分解
Private Function ParseCsvLine(ByVal csvLine As String) As Variant
    Dim result() As String, n As Long, i As Long, ch As String, cur As String, inQ As Boolean
    ReDim result(0)
    For i = 1 To Len(csvLine)
        ch = Mid$(csvLine, i, 1)
        If inQ Then
            If ch = """" Then
                If Mid$(csvLine, i + 1, 1) = """" Then
                    cur = cur & """": i = i + 1
                Else
                    inQ = False
                End If
            Else
                cur = cur & ch
            End If
        ElseIf ch = """" Then
            inQ = True
        ElseIf ch = "," Then
            result(n) = cur: cur = "": n = n + 1
            ReDim Preserve result(n)
        Else
            cur = cur & ch
        End If
    Next i
    result(n) = cur
    ParseCsvLine = result
End Function
