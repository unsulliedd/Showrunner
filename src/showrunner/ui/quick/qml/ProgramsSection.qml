import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// Programs: every external program with its state, version and place, what it turns on, and the ways to locate,
// download or look it up. A download is confirmed first; an installer starts only after a second yes.
SettingsPage {
    id: page

    readonly property var programs: app.settings.programs

    title: Strings.t("prefs.programs.title")
    lead: Strings.t("prefs.programs.lead")

    actions: [
        ActionButton {
            objectName: "recheck"
            kind: "ghost"
            iconName: "resume"
            text: Strings.t("prefs.programs.recheck")
            enabled: !page.programs.busy
            onClicked: page.programs.check_all()
        }
    ]

    Repeater {
        model: page.programs.rows

        delegate: Rectangle {
            id: card

            required property var modelData

            Layout.fillWidth: true
            implicitHeight: body.implicitHeight + 2 * Theme.space_lg
            radius: Theme.radius_md
            color: Theme.panel_2
            border.width: Theme.stroke
            border.color: modelData.id === page.programs.focus ? Theme.control : Theme.line
            Accessible.role: Accessible.Grouping
            Accessible.name: modelData.name

            ColumnLayout {
                id: body

                anchors.fill: parent
                anchors.margins: Theme.space_lg
                spacing: Theme.space_sm

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space_md

                    UiText {
                        Layout.fillWidth: true
                        text: card.modelData.name
                        font.weight: Font.DemiBold
                    }

                    Rectangle {
                        width: Theme.dot
                        height: Theme.dot
                        radius: Theme.dot / 2
                        color: card.modelData.tone === "add" ? Theme.add
                             : card.modelData.tone === "change" ? Theme.change
                             : card.modelData.tone === "drop" ? Theme.drop : Theme.faint
                    }

                    UiText {
                        text: card.modelData.state
                        color: Theme.muted
                    }
                }

                Repeater {
                    model: card.modelData.details

                    delegate: UiText {
                        required property string modelData
                        required property int index

                        Layout.fillWidth: true
                        text: modelData
                        mono: index > 0
                        color: Theme.muted
                        font.pixelSize: Theme.text_sm
                    }
                }

                Hint {
                    text: card.modelData.unlocks
                }

                Flow {
                    Layout.fillWidth: true
                    Layout.topMargin: Theme.space_xs
                    spacing: Theme.space_sm

                    ActionButton {
                        text: Strings.t("dependencies.locate")
                        enabled: !page.programs.busy
                        onClicked: page.programs.locate(card.modelData.id)
                    }

                    ActionButton {
                        visible: card.modelData.user_path
                        text: Strings.t("dependencies.forget")
                        enabled: !page.programs.busy
                        onClicked: page.programs.forget(card.modelData.id)
                    }

                    ActionButton {
                        objectName: "download_" + card.modelData.id
                        kind: "primary"
                        text: card.modelData.download
                        iconName: card.modelData.variants.length > 0 ? "down" : ""
                        enabled: !page.programs.busy
                        onClicked: card.modelData.variants.length > 0 ? variants.open()
                                                                       : page.programs.download(card.modelData.id, "")

                        Menu {
                            id: variants

                            y: parent.height + Theme.space_xs
                            padding: Theme.space_sm

                            background: Rectangle {
                                implicitWidth: Theme.menu_width * 1.5
                                radius: Theme.radius_md
                                color: Theme.panel_2
                                border.width: Theme.stroke
                                border.color: Theme.line_strong
                            }

                            Instantiator {
                                model: card.modelData.variants

                                delegate: MenuRow {
                                    required property var modelData

                                    implicitWidth: Theme.menu_width * 1.5
                                    text: modelData.label
                                    onTriggered: page.programs.download(card.modelData.id, modelData.id)
                                }

                                onObjectAdded: (index, object) => variants.insertItem(index, object)
                                onObjectRemoved: (index, object) => variants.removeItem(object)
                            }
                        }
                    }

                    ActionButton {
                        kind: "ghost"
                        iconName: "link"
                        text: Strings.t("dependencies.official_page")
                        onClicked: page.programs.open_page(card.modelData.id)
                    }
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        visible: page.programs.message !== ""
        spacing: Theme.space_md

        Hint {
            objectName: "programsMessage"
            text: page.programs.message
            tone: page.programs.tone
        }

        ProgressLine {
            Layout.preferredWidth: Theme.progress_width
            visible: page.programs.progress >= 0
            value: page.programs.progress
        }

        ActionButton {
            visible: page.programs.cancellable
            kind: "outline"
            text: Strings.t("prefs.programs.cancel")
            onClicked: page.programs.cancel()
        }
    }

    ConfirmPopup {
        id: ask

        objectName: "programQuestion"
        heading: page.programs.question.title || ""
        text: page.programs.question.text || ""
        yes: Strings.t("prefs.programs.yes")
        no: Strings.t("prefs.programs.no")
        onAccepted: page.programs.answer(true)
        onRejected: page.programs.answer(false)
    }

    function askIfWaiting() {
        if (page.programs.question.title !== undefined && !ask.opened)
            ask.open()
    }

    // A question that came while another section showed is asked once Programs shows again.
    Component.onCompleted: askIfWaiting()

    Connections {
        target: page.programs

        function onChanged() {
            page.askIfWaiting()
        }
    }
}
