import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The selected file: its name, what its plans change (and what stays), its title, and its tracks before and after.
ScrollPane {
    id: inspector

    readonly property var file: app.inspector

    contentWidth: availableWidth
    clip: true

    component Heading: UiText {
        color: Theme.faint
        font.pixelSize: Theme.text_xs
        font.weight: Font.DemiBold
        font.letterSpacing: Theme.stroke
    }

    ColumnLayout {
        width: inspector.availableWidth - 2 * Theme.space_lg
        x: Theme.space_lg
        spacing: Theme.space_md

        Item {
            Layout.preferredHeight: Theme.space_sm
        }

        UiText {
            Layout.fillWidth: true
            text: inspector.file.name ?? ""
            font.pixelSize: Theme.text_xl
            font.weight: Font.Bold
        }

        UiText {
            Layout.fillWidth: true
            text: inspector.file.facts ?? ""
            color: Theme.muted
        }

        UiText {
            Layout.fillWidth: true
            mono: true
            text: inspector.file.file ?? ""
            color: Theme.faint
            font.pixelSize: Theme.text_xs
            wrapMode: Text.WrapAnywhere
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space_sm
            implicitHeight: changes.implicitHeight + 2 * Theme.space_lg
            radius: Theme.radius_lg
            color: Theme.panel_2
            border.width: Theme.stroke
            border.color: Theme.line

            ColumnLayout {
                id: changes

                anchors.fill: parent
                anchors.margins: Theme.space_lg
                spacing: Theme.space_md

                RowLayout {
                    Layout.fillWidth: true

                    Heading {
                        Layout.fillWidth: true
                        text: Strings.t("inspector.what_changes")
                    }

                    UiText {
                        text: inspector.file.count ?? 0
                        color: Theme.change
                        font.pixelSize: Theme.text_xs
                        font.weight: Font.DemiBold
                    }
                }

                UiText {
                    Layout.fillWidth: true
                    visible: (inspector.file.changes ?? []).length === 0
                    text: Strings.t("inspector.nothing")
                    color: Theme.muted
                }

                Repeater {
                    model: inspector.file.changes ?? []

                    delegate: RowLayout {
                        required property var modelData

                        Layout.fillWidth: true
                        spacing: Theme.space_md

                        Rectangle {
                            Layout.alignment: Qt.AlignTop
                            Layout.preferredWidth: Theme.row_sm
                            Layout.preferredHeight: Theme.row_sm
                            radius: Theme.radius_md
                            color: Theme.change_soft

                            Icon {
                                anchors.centerIn: parent
                                name: modelData.icon
                                size: Theme.icon_sm
                                color: Theme.change
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Theme.space_xs

                            UiText {
                                Layout.fillWidth: true
                                text: modelData.text
                                font.weight: Font.Medium
                                wrapMode: Text.WordWrap
                            }

                            UiText {
                                Layout.fillWidth: true
                                visible: modelData.detail !== ""
                                text: modelData.detail
                                color: Theme.faint
                                font.pixelSize: Theme.text_sm
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space_md

                    Item {
                        Layout.preferredWidth: Theme.row_sm
                        Layout.preferredHeight: Theme.row_sm

                        Icon {
                            anchors.centerIn: parent
                            name: "check"
                            size: Theme.icon_sm
                        }
                    }

                    UiText {
                        Layout.fillWidth: true
                        text: inspector.file.stays ?? ""
                        color: Theme.muted
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space_sm

            Heading {
                Layout.fillWidth: true
                text: Strings.t("inspector.title")
            }

            UiText {
                visible: (inspector.file.title_new ?? "") !== ""
                text: Strings.t("inspector.from_template")
                color: Theme.change
                font.pixelSize: Theme.text_xs
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Theme.row_lg
            radius: Theme.radius_md
            color: Theme.well
            border.width: Theme.stroke
            border.color: (inspector.file.title_new ?? "") !== "" ? Theme.change : Theme.line_strong

            UiText {
                anchors.fill: parent
                anchors.leftMargin: Theme.space_md
                anchors.rightMargin: Theme.space_md
                readonly property string title: inspector.file.title_new || inspector.file.title_now || ""
                text: title !== "" ? title : (inspector.file.title_placeholder ?? "")
                color: title !== "" ? Theme.ink : Theme.faint
                font.italic: title === ""
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space_sm

            Heading {
                Layout.fillWidth: true
                text: Strings.t("inspector.tracks")
            }

            UiText {
                text: inspector.file.track_count ?? ""
                color: Theme.muted
                font.pixelSize: Theme.text_xs
            }
        }

        Repeater {
            model: inspector.file.tracks ?? []

            delegate: RowLayout {
                id: track

                required property var modelData
                readonly property bool dropped: modelData.state === "dropped"

                Layout.fillWidth: true
                Layout.preferredHeight: Theme.list_row
                spacing: Theme.space_md

                Icon {
                    name: track.modelData.state === "added" ? "plus"
                        : track.modelData.kind === "video" ? "video"
                        : track.modelData.kind === "audio" ? "audio" : "subs"
                    size: Theme.icon_sm
                    color: track.modelData.state === "added" ? Theme.add : Theme.faint
                }

                CodeBadge {
                    code: track.modelData.code
                    look: track.modelData.state
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space_xs

                    UiText {
                        Layout.fillWidth: true
                        text: track.modelData.title
                        color: track.dropped ? Theme.drop : Theme.ink
                        font.strikeout: track.dropped
                        font.weight: Font.Medium
                    }

                    Row {
                        Layout.fillWidth: true
                        spacing: Theme.space_sm
                        clip: true

                        UiText {
                            text: track.modelData.name
                            color: track.dropped ? Theme.drop : Theme.muted
                            font.pixelSize: Theme.text_sm
                            font.strikeout: track.dropped || track.modelData.new_name !== ""
                        }

                        UiText {
                            visible: track.modelData.new_name !== ""
                            text: Strings.t("inspector.becomes")
                            color: Theme.faint
                            font.pixelSize: Theme.text_sm
                        }

                        UiText {
                            visible: track.modelData.new_name !== ""
                            text: track.modelData.new_name
                            color: Theme.change
                            font.pixelSize: Theme.text_sm
                        }
                    }
                }

                Icon {
                    visible: track.modelData.default
                    name: "star_on"
                    size: Theme.icon_sm
                    color: Theme.change
                }

                Rectangle {
                    visible: track.modelData.forced
                    width: Theme.icon_md
                    height: Theme.icon_md
                    radius: Theme.radius_sm
                    color: Theme.ink

                    UiText {
                        anchors.centerIn: parent
                        text: Strings.t("tracks.forced_mark")
                        color: Theme.ground
                        font.pixelSize: Theme.text_xs
                        font.weight: Font.Bold
                    }
                }
            }
        }

        Item {
            Layout.preferredHeight: Theme.space_lg
        }
    }
}
