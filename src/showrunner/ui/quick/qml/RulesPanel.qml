import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The batch's track rules in the order they apply: choices made on Overview and Tracks marked "from the matrix",
// hand-written ones beside them. Drag a card by its grip to reorder; the pause button keeps a rule but stops it. New
// rule and the pencil of a hand-written rule open the editor in place of the list.
Item {
    id: panel

    readonly property bool editing: app.rule_editor.form.open
    // What had the focus when the editor opened, so that closing it gives the focus back.
    property Item opener: null
    // What a delegate reads for a moment after its rule is gone, until the list drops it.
    readonly property var none: ({
            "enabled": true,
            "from_choice": true,
            "label": "",
            "parts": [],
            "fits": "",
            "source": ""
        })

    onEditingChanged: if (!editing && opener) opener.forceActiveFocus()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_lg

        UiText {
            Layout.fillWidth: true
            visible: !panel.editing
            text: Strings.t("rules.intro")
            color: Theme.muted
            font.pixelSize: Theme.text_sm
            wrapMode: Text.WordWrap
        }

        ActionButton {
            objectName: "addRule"
            visible: !panel.editing
            size: Theme.row_sm
            iconName: "plus"
            text: Strings.t("rules.add")
            onClicked: {
                panel.opener = this
                app.rule_editor.open_new()
            }
        }

        UiText {
            Layout.fillWidth: true
            visible: !panel.editing && app.rules.length === 0
            text: Strings.t("rules.empty")
            color: Theme.faint
            font.pixelSize: Theme.text_sm
            wrapMode: Text.WordWrap
        }

        ListView {
            id: list

            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !panel.editing
            clip: true
            spacing: Theme.space_md
            // A count, not the rules: a change of one rule then updates its delegate in place and keeps the focus.
            model: app.rules.length
            boundsBehavior: Flickable.StopAtBounds
            // The list stays put while a card is dragged, so the drag moves the card, not the list.
            interactive: !dragging

            property bool dragging: false

            // The row whose card covers `y` (in the list's content), or the nearest one in a gap between cards.
            function rowAt(y) {
                const found = indexAt(width / 2, y)
                if (found >= 0)
                    return found
                const below = indexAt(width / 2, y + spacing)
                if (below >= 0)
                    return below
                return y < 0 ? 0 : count - 1
            }
            ScrollBar.vertical: Scroller {}

            delegate: Item {
                id: entry

                required property int index
                readonly property var rule: app.rules[index] || panel.none

                width: list.width
                height: card.height
                z: grip.active ? 1 : 0

                Rectangle {
                    id: card

                    width: parent.width
                    height: body.implicitHeight + 2 * Theme.space_md
                    radius: Theme.radius_lg
                    color: Theme.panel_2
                    border.width: Theme.stroke
                    border.color: grip.active ? Theme.control : Theme.line
                    opacity: entry.rule.enabled ? 1 : 0.5
                    transform: Translate {
                        y: grip.active ? grip.activeTranslation.y : 0
                    }

                    RowLayout {
                        id: body

                        anchors.fill: parent
                        anchors.margins: Theme.space_md
                        spacing: Theme.space_md

                        Item {
                            objectName: "ruleGrip"
                            Layout.alignment: Qt.AlignTop
                            Layout.preferredWidth: Theme.icon_md
                            Layout.preferredHeight: Theme.row_sm
                            Accessible.role: Accessible.Grip
                            Accessible.name: Strings.t("rules.drag")

                            Icon {
                                anchors.centerIn: parent
                                name: "grip"
                                size: Theme.icon_sm
                            }

                            DragHandler {
                                id: grip

                                target: null
                                xAxis.enabled: false
                                property real moved: 0

                                onActiveTranslationChanged: if (active) moved = activeTranslation.y
                                onActiveChanged: {
                                    list.dragging = active
                                    if (active)
                                        return
                                    const centre = entry.mapToItem(list.contentItem, 0, entry.height / 2 + moved)
                                    app.move_rule(entry.index, list.rowAt(centre.y))
                                    moved = 0
                                }
                            }
                        }

                        UiText {
                            Layout.alignment: Qt.AlignTop
                            Layout.preferredHeight: Theme.row_sm
                            text: entry.index + 1
                            color: Theme.faint
                            font.pixelSize: Theme.text_xs
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Theme.space_sm

                            UiText {
                                Layout.fillWidth: true
                                visible: entry.rule.label !== ""
                                text: entry.rule.label
                                color: Theme.muted
                                font.pixelSize: Theme.text_sm
                                font.weight: Font.DemiBold
                            }

                            RuleSentence {
                                Layout.fillWidth: true
                                parts: entry.rule.parts
                            }

                            Row {
                                spacing: Theme.space_md

                                UiText {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: entry.rule.fits
                                    color: Theme.faint
                                    font.pixelSize: Theme.text_xs
                                }

                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: source.implicitWidth + 2 * Theme.space_sm
                                    height: Theme.pill
                                    radius: Theme.radius_sm
                                    color: "transparent"
                                    border.width: Theme.stroke
                                    border.color: entry.rule.from_choice ? Theme.control : Theme.line_strong

                                    UiText {
                                        id: source

                                        anchors.centerIn: parent
                                        text: entry.rule.source
                                        color: entry.rule.from_choice ? Theme.control : Theme.muted
                                        font.pixelSize: Theme.text_xs
                                    }
                                }
                            }
                        }

                        IconButton {
                            Layout.alignment: Qt.AlignTop
                            implicitWidth: Theme.row_sm
                            implicitHeight: Theme.row_sm
                            iconName: entry.rule.enabled ? "pause" : "play"
                            active: !entry.rule.enabled
                            label: entry.rule.enabled ? Strings.t("rules.pause") : Strings.t("rules.resume")
                            onClicked: app.pause_rule(entry.index, entry.rule.enabled)
                        }

                        IconButton {
                            objectName: "editRule"
                            Layout.alignment: Qt.AlignTop
                            visible: !entry.rule.from_choice
                            implicitWidth: Theme.row_sm
                            implicitHeight: Theme.row_sm
                            iconName: "edit"
                            label: Strings.t("rules.edit")
                            onClicked: {
                                panel.opener = this
                                app.rule_editor.open_rule(entry.index)
                            }
                        }

                        IconButton {
                            objectName: "removeRule"
                            Layout.alignment: Qt.AlignTop
                            visible: !entry.rule.from_choice
                            implicitWidth: Theme.row_sm
                            implicitHeight: Theme.row_sm
                            iconName: "x"
                            label: Strings.t("rules.delete")
                            onClicked: app.remove_rule(entry.index)
                        }
                    }
                }
            }
        }

        Loader {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: panel.editing
            active: panel.editing
            source: "RuleEditor.qml"
        }

        SaveBar {
            Layout.fillWidth: true
            visible: app.profile_edited && !panel.editing
            title: Strings.f("rules.unsaved.title", {"name": app.profile})
            lead: Strings.t("rules.unsaved.lead")
            action: Strings.t("profile.save")
        }
    }
}
