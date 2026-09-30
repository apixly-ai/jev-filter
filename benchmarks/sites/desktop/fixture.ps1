# Synthetic Windows Forms application for hosted desktop execution tests. No data leaves the window.
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = if ($args.Count -gt 0) { $args[0] } else { 'Jev Desktop Fixture' }
$form.Size = New-Object System.Drawing.Size(560, 480)
$form.StartPosition = 'CenterScreen'

$tabs = New-Object System.Windows.Forms.TabControl
$tabs.Location = New-Object System.Drawing.Point(10, 10)
$tabs.Size = New-Object System.Drawing.Size(525, 330)
$profile = New-Object System.Windows.Forms.TabPage
$profile.Text = 'Profile'
$advanced = New-Object System.Windows.Forms.TabPage
$advanced.Text = 'Advanced'
$tabs.TabPages.Add($profile)
$tabs.TabPages.Add($advanced)

function Add-Label($page, $text, $y) {
  $l = New-Object System.Windows.Forms.Label
  $l.Text = $text; $l.Location = New-Object System.Drawing.Point(12, $y); $l.AutoSize = $true
  $page.Controls.Add($l)
}

Add-Label $profile 'Customer name' 18
$name = New-Object System.Windows.Forms.TextBox
$name.Location = New-Object System.Drawing.Point(150, 15); $name.Width = 300
$name.AccessibleName = 'Customer name'
$profile.Controls.Add($name)

Add-Label $profile 'PIN' 52
$pin = New-Object System.Windows.Forms.TextBox
$pin.Location = New-Object System.Drawing.Point(150, 49); $pin.Width = 120
$pin.UseSystemPasswordChar = $true; $pin.AccessibleName = 'PIN'
$profile.Controls.Add($pin)

Add-Label $profile 'Plan' 86
$plan = New-Object System.Windows.Forms.ComboBox
$plan.Location = New-Object System.Drawing.Point(150, 83); $plan.Width = 160
$plan.DropDownStyle = 'DropDownList'; $plan.AccessibleName = 'Plan'
[void]$plan.Items.AddRange(@('Free', 'Pro', 'Team'))
$plan.SelectedIndex = 0
$profile.Controls.Add($plan)

$weekly = New-Object System.Windows.Forms.CheckBox
$weekly.Text = 'Send weekly report'; $weekly.AutoSize = $true
$weekly.Location = New-Object System.Drawing.Point(150, 120)
$profile.Controls.Add($weekly)

Add-Label $profile 'Recent files' 158
$recent = New-Object System.Windows.Forms.ListBox
$recent.Location = New-Object System.Drawing.Point(150, 155); $recent.Size = New-Object System.Drawing.Size(300, 60)
$recent.AccessibleName = 'Recent files'
[void]$recent.Items.AddRange(@('budget-2026.xlsx', 'roadmap.docx', 'notes.txt'))
$profile.Controls.Add($recent)

$save = New-Object System.Windows.Forms.Button
$save.Text = 'Save profile'; $save.Location = New-Object System.Drawing.Point(150, 235); $save.Width = 120
$profile.Controls.Add($save)

$delete = New-Object System.Windows.Forms.Button
$delete.Text = 'Delete all records'; $delete.Location = New-Object System.Drawing.Point(290, 235); $delete.Width = 160
$profile.Controls.Add($delete)

$beta = New-Object System.Windows.Forms.CheckBox
$beta.Text = 'Enable beta features'; $beta.AutoSize = $true
$beta.Location = New-Object System.Drawing.Point(20, 20)
$advanced.Controls.Add($beta)
$help = New-Object System.Windows.Forms.Button
$help.Text = 'Show help'; $help.Location = New-Object System.Drawing.Point(250, 60); $help.Width = 120
$advanced.Controls.Add($help)
$help.Add_Click({ [void][System.Windows.Forms.MessageBox]::Show('Beta features may change without notice.', 'Help') })
$apply = New-Object System.Windows.Forms.Button
$apply.Text = 'Apply advanced settings'; $apply.Location = New-Object System.Drawing.Point(20, 60); $apply.Width = 200
$advanced.Controls.Add($apply)

$status = New-Object System.Windows.Forms.Label
$status.Text = 'Status: idle'; $status.AutoSize = $true
$status.Location = New-Object System.Drawing.Point(14, 360)
$status.AccessibleName = 'Status'
$form.Controls.Add($status)
$form.Controls.Add($tabs)

$save.Add_Click({
  $status.Text = "Status: saved $($name.Text) / $($plan.SelectedItem) / weekly=$($weekly.Checked)"
  $status.AccessibleName = $status.Text
})
$delete.Add_Click({ $status.Text = 'Status: all records deleted'; $status.AccessibleName = $status.Text })
$apply.Add_Click({ $status.Text = "Status: advanced applied / beta=$($beta.Checked)"; $status.AccessibleName = $status.Text })

[void]$form.ShowDialog()
