import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The Names companion panel: the built-in tokens by what they read, the user's own tokens, "+" for a new one and the
// editor of the one open under them. Each shows its value on the selected file.
Item {
    id: panel

    readonly property var editor: app.tokens.editor

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_md

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_sm

            FindField {
                Layout.fillWidth: true
                placeholderText: Strings.t("tokens.search")
                text: app.token_query
                onTextEdited: app.token_query = text
            }

            IconButton {
                objectName: "addToken"
                iconName: "plus"
                label: Strings.t("tokens.add")
                onClicked: app.add_token()
            }
        }

        ScrollPane {
            id: scroll

            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth

            ColumnLayout {
                width: scroll.availableWidth
                spacing: Theme.space_sm

                Repeater {
                    model: app.tokens.groups

                    delegate: ColumnLayout {
                        id: group

                        required property var modelData

                        Layout.fillWidth: true
                        Layout.topMargin: Theme.space_md
                        spacing: Theme.space_xs

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.space_md

                            UiText {
                                Layout.fillWidth: true
                                text: group.modelData.label
                                color: Theme.faint
                                font.pixelSize: Theme.text_xs
                                font.weight: Font.DemiBold
                                font.letterSpacing: Theme.stroke
                                font.capitalization: Font.AllUppercase
                            }

                            HelpTip {
                                objectName: "separatorsTip"
                                visible: group.modelData.key === "separator"
                                topic: "separators"
                            }

                            PlaceMark {
                                objectName: "customTokensMark"
                                visible: group.modelData.key === "custom" && text !== ""
                                choice: app.field_marks["naming.custom_tokens"] || ({})
                            }
                        }

                        // Separators are small and many, so they sit side by side.
                        Flow {
                            Layout.fillWidth: true
                            visible: group.modelData.key === "separator"
                            spacing: Theme.space_sm

                            Repeater {
                                model: group.modelData.key === "separator" ? group.modelData.tokens : []

                                delegate: SeparatorChip {
                                    required property var modelData

                                    separator: modelData
                                }
                            }
                        }

                        Repeater {
                            model: group.modelData.key === "separator" ? [] : group.modelData.tokens

                            delegate: TokenRow {
                                required property var modelData

                                Layout.fillWidth: true
                                token: modelData
                            }
                        }

                        UiText {
                            Layout.fillWidth: true
                            visible: group.modelData.key === "custom" && group.modelData.tokens.length === 0
                            text: Strings.t("tokens.custom_empty")
                            color: Theme.faint
                            font.pixelSize: Theme.text_sm
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }

        // Below the list rather than in it, so a token opened from "+" is in view at once.
        Loader {
            Layout.fillWidth: true
            active: panel.editor.index !== undefined
            visible: active

            sourceComponent: TokenEditor {
                token: panel.editor
            }
        }
    }
}
