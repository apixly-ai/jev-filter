"""Synthetic AppKit application mirroring fixture.ps1 for macOS hosted-execution tests.

Needs pyobjc (jev-filter[desktop]). No data leaves the window.
"""

import sys

import AppKit
import objc
from Foundation import NSMakeRect, NSObject

TITLE = sys.argv[1] if len(sys.argv) > 1 else "Jev Desktop Fixture"


class Controller(NSObject):
    def init(self):
        self = objc.super(Controller, self).init()
        return self

    @objc.python_method
    def build(self):
        style = AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
        self.window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(200, 200, 560, 420), style, AppKit.NSBackingStoreBuffered, False
        )
        self.window.setTitle_(TITLE)
        content = self.window.contentView()
        tabs = AppKit.NSTabView.alloc().initWithFrame_(NSMakeRect(10, 60, 540, 350))
        profile = AppKit.NSTabViewItem.alloc().initWithIdentifier_("profile")
        profile.setLabel_("Profile")
        advanced = AppKit.NSTabViewItem.alloc().initWithIdentifier_("advanced")
        advanced.setLabel_("Advanced")
        tabs.addTabViewItem_(profile)
        tabs.addTabViewItem_(advanced)
        view = profile.view()

        def label(text, y):
            field = AppKit.NSTextField.labelWithString_(text)
            field.setFrame_(NSMakeRect(12, y, 130, 22))
            view.addSubview_(field)

        label("Customer name", 270)
        self.name = AppKit.NSTextField.alloc().initWithFrame_(NSMakeRect(150, 268, 300, 24))
        self.name.cell().setAccessibilityLabel_("Customer name")
        view.addSubview_(self.name)
        label("PIN", 236)
        pin = AppKit.NSSecureTextField.alloc().initWithFrame_(NSMakeRect(150, 234, 120, 24))
        view.addSubview_(pin)
        label("Plan", 202)
        self.plan = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(150, 198, 160, 28), False
        )
        self.plan.addItemsWithTitles_(["Free", "Pro", "Team"])
        self.plan.setAccessibilityLabel_("Plan")
        view.addSubview_(self.plan)
        self.weekly = AppKit.NSButton.checkboxWithTitle_target_action_(
            "Send weekly report", None, None
        )
        self.weekly.setFrame_(NSMakeRect(150, 166, 220, 24))
        view.addSubview_(self.weekly)
        save = AppKit.NSButton.buttonWithTitle_target_action_("Save profile", self, "save:")
        save.setFrame_(NSMakeRect(150, 120, 130, 32))
        view.addSubview_(save)
        delete = AppKit.NSButton.buttonWithTitle_target_action_(
            "Delete all records", self, "deleteAll:"
        )
        delete.setFrame_(NSMakeRect(290, 120, 160, 32))
        view.addSubview_(delete)
        aview = advanced.view()
        self.beta = AppKit.NSButton.checkboxWithTitle_target_action_(
            "Enable beta features", None, None
        )
        self.beta.setFrame_(NSMakeRect(20, 250, 220, 24))
        aview.addSubview_(self.beta)
        apply = AppKit.NSButton.buttonWithTitle_target_action_(
            "Apply advanced settings", self, "apply:"
        )
        apply.setFrame_(NSMakeRect(20, 210, 220, 32))
        aview.addSubview_(apply)
        self.status = AppKit.NSTextField.labelWithString_("Status: idle")
        self.status.setFrame_(NSMakeRect(14, 20, 520, 24))
        content.addSubview_(tabs)
        content.addSubview_(self.status)
        self.window.makeKeyAndOrderFront_(None)

    def save_(self, _):
        weekly = "True" if self.weekly.state() == AppKit.NSControlStateValueOn else "False"
        self.status.setStringValue_(
            f"Status: saved {self.name.stringValue()} / {self.plan.titleOfSelectedItem()} / weekly={weekly}"
        )

    def deleteAll_(self, _):
        self.status.setStringValue_("Status: all records deleted")

    def apply_(self, _):
        beta = "True" if self.beta.state() == AppKit.NSControlStateValueOn else "False"
        self.status.setStringValue_(f"Status: advanced applied / beta={beta}")


app = AppKit.NSApplication.sharedApplication()
app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
controller = Controller.alloc().init()
controller.build()
app.activateIgnoringOtherApps_(True)
app.run()
