import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The Subtitles place: the box of the place's subtitle settings, one row each in the order of the work, then one row
// per file with its subtitles now and the finished subtitles its plan makes. A received value is drawn muted with
// where it comes from; the row menu follows the parent again or makes "as it is" the place's own value.
Item {
    id: place

    // Read once: each read of the property converts the whole view for QML.
    readonly property var view: app.subtitles
    readonly property var rows: view.rows ?? []
    readonly property var files: view.files ?? []

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_lg

        Rectangle {
            objectName: "subtitlesBox"
            Layout.fillWidth: true
            implicitHeight: rows.implicitHeight + 2 * Theme.space_lg
            radius: Theme.radius_lg
            color: Theme.panel
            border.width: Theme.stroke
            border.color: Theme.line

            ColumnLayout {
                id: rows

                anchors.fill: parent
                anchors.margins: Theme.space_lg
                spacing: Theme.space_md

                UiText {
                    Layout.fillWidth: true
                    text: place.view.title ?? ""
                    font.weight: Font.DemiBold
                }

                UiText {
                    Layout.fillWidth: true
                    text: Strings.t("subtitles.box.lead")
                    color: Theme.muted
                    font.pixelSize: Theme.text_sm
                    wrapMode: Text.WordWrap
                }

                // Counts, not the rows: a new view then updates the delegates in place, so a segment keeps the
                // keyboard and an open row menu keeps its row.
                Repeater {
                    model: place.rows.length

                    delegate: ColumnLayout {
                        id: row

                        required property int index
                        readonly property var modelData: place.rows[index]

                        objectName: "subtitleRow_" + modelData.key
                        Layout.fillWidth: true
                        spacing: Theme.space_xs

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.minimumHeight: Theme.row_lg
                            spacing: Theme.space_md

                            UiText {
                                Layout.preferredWidth: Theme.matrix_label
                                text: row.modelData.label
                                color: Theme.muted
                                font.pixelSize: Theme.text_sm
                            }

                            Segmented {
                                visible: row.modelData.choices !== undefined
                                model: row.modelData.choices ?? []
                                current: row.modelData.value ?? ""
                                name: row.modelData.label
                                onPicked: key => app.set_subtitle_choice(row.modelData.key, key)
                            }

                            Flow {
                                visible: row.modelData.items !== undefined
                                Layout.fillWidth: true
                                spacing: Theme.space_sm

                                Repeater {
                                    model: row.modelData.items ?? []

                                    delegate: Row {
                                        id: item

                                        required property var modelData

                                        spacing: Theme.space_xs

                                        CodeBadge {
                                            anchors.verticalCenter: parent.verticalCenter
                                            code: item.modelData.label
                                            look: item.modelData.off ? "dropped" : "kept"
                                            Accessible.name: item.modelData.name
                                        }

                                        UiText {
                                            anchors.verticalCenter: parent.verticalCenter
                                            visible: row.modelData.key === "cleanup"
                                            text: item.modelData.name
                                            color: item.modelData.own ? Theme.ink : Theme.muted
                                            font.pixelSize: Theme.text_sm
                                            font.strikeout: item.modelData.off
                                        }

                                        UiText {
                                            anchors.verticalCenter: parent.verticalCenter
                                            visible: row.modelData.key === "cleanup" && !item.modelData.missing
                                            text: item.modelData.languages ?? ""
                                            color: Theme.faint
                                            font.pixelSize: Theme.text_xs
                                        }

                                        UiText {
                                            objectName: "cleanupMissing"
                                            anchors.verticalCenter: parent.verticalCenter
                                            visible: item.modelData.missing === true
                                            text: Strings.t("cleanup.missing")
                                            color: Theme.change
                                            font.pixelSize: Theme.text_xs
                                        }

                                        IconButton {
                                            anchors.verticalCenter: parent.verticalCenter
                                            implicitWidth: Theme.row_sm
                                            implicitHeight: Theme.row_sm
                                            iconName: row.modelData.key === "cleanup" ? (item.modelData.off ? "play" : "pause") : (item.modelData.off ? "plus" : "x")
                                            active: item.modelData.off
                                            label: item.modelData.off ? Strings.t("subtitles.item.back") : Strings.t("subtitles.item.off")
                                            enabled: !app.locked
                                            onClicked: app.toggle_subtitle_item(row.modelData.key, item.modelData.key)
                                        }

                                        PlaceMark {
                                            anchors.verticalCenter: parent.verticalCenter
                                            choice: item.modelData.mark
                                        }
                                    }
                                }

                                ActionButton {
                                    visible: row.modelData.key === "wanted"
                                    kind: "ghost"
                                    size: Theme.row_sm
                                    iconName: "plus"
                                    text: Strings.t("subtitles.wanted.add")
                                    enabled: !app.locked
                                    onClicked: app.pick_wanted_language()
                                }

                                ActionButton {
                                    id: addSet

                                    objectName: "cleanupAdd"
                                    visible: row.modelData.key === "cleanup"
                                    kind: "ghost"
                                    size: Theme.row_sm
                                    iconName: "plus"
                                    text: Strings.t("cleanup.add")
                                    enabled: !app.locked && (row.modelData.add ?? []).length > 0
                                    onClicked: addMenu.popup(addSet, 0, addSet.height)
                                }

                                ActionMenu {
                                    id: addMenu

                                    actions: row.modelData.add ?? []
                                    onPicked: key => Qt.callLater(() => app.add_rule_set(key))
                                }

                                ActionButton {
                                    objectName: "cleanupEdit"
                                    visible: row.modelData.key === "cleanup"
                                    kind: "ghost"
                                    size: Theme.row_sm
                                    iconName: "edit"
                                    text: Strings.t("cleanup.edit")
                                    onClicked: app.edit_rule_sets("")
                                }

                                UiText {
                                    objectName: "cleanupCount"
                                    visible: row.modelData.key === "cleanup" && (row.modelData.count ?? "") !== ""
                                    text: row.modelData.count ?? ""
                                    color: Theme.muted
                                    font.pixelSize: Theme.text_xs
                                }

                                UiText {
                                    visible: (row.modelData.items ?? []).length === 0 && row.modelData.key !== "wanted"
                                    text: row.modelData.empty ?? ""
                                    color: Theme.faint
                                    font.pixelSize: Theme.text_sm
                                }
                            }

                            ColumnLayout {
                                visible: row.modelData.text !== undefined
                                Layout.fillWidth: true
                                spacing: 0

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.space_sm

                                    UiText {
                                        objectName: "subtitleValue_" + row.modelData.key
                                        Layout.fillWidth: true
                                        text: row.modelData.text ?? ""
                                        color: row.modelData.received ? Theme.muted : Theme.ink
                                        font.pixelSize: Theme.text_sm
                                        elide: Text.ElideRight
                                    }

                                    ActionButton {
                                        id: pickValue

                                        objectName: row.modelData.key + "Pick"
                                        visible: row.modelData.pick !== undefined
                                        kind: "ghost"
                                        size: Theme.row_sm
                                        iconName: "down"
                                        text: Strings.t("subtitles.reference.pick")
                                        enabled: !app.locked
                                        onClicked: valueMenu.popup(pickValue, 0, pickValue.height)
                                    }

                                    ActionMenu {
                                        id: valueMenu

                                        actions: row.modelData.pick ?? []
                                        onPicked: key => Qt.callLater(() => row.modelData.key === "model" ? app.pick_model(key) : app.pick_reference(key))
                                    }
                                }

                                // What each file works against, and the files the chosen track is missing in.
                                UiText {
                                    objectName: "referenceFound"
                                    Layout.fillWidth: true
                                    visible: (row.modelData.found ?? "") !== ""
                                    text: row.modelData.found ?? ""
                                    color: Theme.faint
                                    font.pixelSize: Theme.text_xs
                                    elide: Text.ElideRight
                                }

                                UiText {
                                    objectName: "referenceFallbacks"
                                    Layout.fillWidth: true
                                    visible: (row.modelData.fallbacks ?? "") !== ""
                                    text: row.modelData.fallbacks ?? ""
                                    color: Theme.change
                                    font.pixelSize: Theme.text_xs
                                    elide: Text.ElideRight
                                }
                            }

                            Item {
                                visible: row.modelData.choices !== undefined
                                Layout.fillWidth: true
                            }

                            // The row's work is left out where no engine can do it.
                            UiText {
                                objectName: "subtitleNote_" + row.modelData.key
                                visible: text !== ""
                                text: row.modelData.note ?? ""
                                color: Theme.change
                                font.pixelSize: Theme.text_xs
                                elide: Text.ElideRight
                            }

                            PlaceMark {
                                Layout.maximumWidth: Theme.track_mark_width
                                choice: app.field_marks["subtitles." + row.modelData.key] || ({})
                            }

                            IconButton {
                                id: more

                                objectName: "subtitleMenu_" + row.modelData.key
                                visible: (place.view.follow ?? "") !== ""
                                implicitWidth: Theme.row_sm
                                implicitHeight: Theme.row_sm
                                iconName: "down"
                                label: row.modelData.label
                                enabled: !app.locked
                                onClicked: menu.popup(more, 0, more.height)
                            }

                            ActionMenu {
                                id: menu

                                actions: [
                                    {"key": "follow", "text": place.view.follow ?? "", "enabled": row.modelData.own},
                                    {"key": "as_it_is", "text": Strings.t("subtitles.menu.as_it_is"), "enabled": true}
                                ]
                                onPicked: key => Qt.callLater(() => key === "follow" ? app.follow_subtitles(row.modelData.key) : app.subtitles_as_it_is(row.modelData.key))
                            }
                        }

                        // The chosen engine's settings: the two thresholds, then its own, each marked by where its value
                        // comes from; an empty field shows what the place receives, or the engine's default.
                        Flow {
                            objectName: "syncSettings"
                            Layout.fillWidth: true
                            Layout.leftMargin: Theme.matrix_label + Theme.space_md
                            visible: (row.modelData.settings ?? []).length > 0
                            spacing: Theme.space_md

                            // A count, as the rows are: a new view updates the fields in place, so one keeps the keyboard
                            // while the field before it is committed.
                            Repeater {
                                model: (row.modelData.settings ?? []).length

                                delegate: Row {
                                    id: setting

                                    required property int index
                                    readonly property var modelData: row.modelData.settings[index]

                                    spacing: Theme.space_sm

                                    UiText {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: setting.modelData.label
                                        color: Theme.muted
                                        font.pixelSize: Theme.text_xs
                                    }

                                    InputField {
                                        objectName: "syncSetting_" + setting.modelData.key
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: setting.modelData.choices === undefined
                                        implicitWidth: Theme.matrix_label
                                        mono: true
                                        label: setting.modelData.label
                                        placeholderText: setting.modelData.placeholder
                                        text: setting.modelData.value
                                        enabled: !app.locked
                                        // The view decides what is taken (a number, "." or ","); the field shows its answer
                                        // again, so a refused entry does not stay on screen.
                                        onEditingFinished: {
                                            app.set_sync_setting(setting.modelData.key, text)
                                            text = Qt.binding(() => setting.modelData.value)
                                        }
                                    }

                                    Segmented {
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: setting.modelData.choices !== undefined
                                        model: setting.modelData.choices ?? []
                                        current: setting.modelData.current ?? ""
                                        name: setting.modelData.label
                                        onPicked: key => app.set_sync_setting(setting.modelData.key, key)
                                    }

                                    PlaceMark {
                                        anchors.verticalCenter: parent.verticalCenter
                                        choice: setting.modelData.mark
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            UiText {
                Layout.preferredWidth: Theme.matrix_label
                text: Strings.t("subtitles.list.file")
                color: Theme.faint
                font.pixelSize: Theme.text_xs
            }

            UiText {
                Layout.preferredWidth: Theme.matrix_label
                text: Strings.t("subtitles.list.now")
                color: Theme.faint
                font.pixelSize: Theme.text_xs
            }

            UiText {
                Layout.fillWidth: true
                text: Strings.t("subtitles.list.plan")
                color: Theme.faint
                font.pixelSize: Theme.text_xs
            }
        }

        ScrollPane {
            id: scroll

            objectName: "subtitleFiles"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            Column {
                width: scroll.availableWidth

                Repeater {
                    model: place.files.length

                    delegate: Item {
                        id: file

                        required property int index
                        readonly property var modelData: place.files[index]

                        width: parent.width
                        height: Math.max(Theme.list_row, plans.implicitHeight + Theme.space_md)

                        // The selected file is the one the Lines panel and the Inspector show.
                        Rectangle {
                            anchors.fill: parent
                            z: -1
                            radius: Theme.radius_md
                            color: file.modelData.path === app.focus_path ? Theme.select : "transparent"

                            MouseArea {
                                objectName: "subtitleFile_" + file.index
                                anchors.fill: parent
                                onClicked: app.focus_file(file.modelData.path)
                            }
                        }

                        RowLayout {
                            anchors.fill: parent
                            spacing: Theme.space_md

                            UiText {
                                Layout.preferredWidth: Theme.matrix_label
                                text: file.modelData.number !== "" ? file.modelData.number + "  " + file.modelData.file : file.modelData.file
                                elide: Text.ElideMiddle
                                font.pixelSize: Theme.text_sm
                            }

                            UiText {
                                Layout.preferredWidth: Theme.matrix_label
                                text: file.modelData.now.join("  ")
                                color: Theme.muted
                                mono: true
                                font.pixelSize: Theme.text_xs
                                elide: Text.ElideRight
                            }

                            Column {
                                id: plans

                                Layout.fillWidth: true

                                UiText {
                                    visible: file.modelData.plan.length === 0
                                    text: Strings.t("tracks.rule.as_it_is")
                                    color: Theme.faint
                                    font.pixelSize: Theme.text_sm
                                }

                                Repeater {
                                    model: file.modelData.plan

                                    delegate: Row {
                                        required property var modelData

                                        spacing: Theme.space_sm

                                        CodeBadge {
                                            code: modelData.code
                                            look: modelData.cannot !== "" ? "dropped" : "kept"
                                        }

                                        UiText {
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: modelData.cannot === "" ? modelData.steps : modelData.steps === "" ? modelData.cannot : modelData.steps + " " + Strings.t("status.separator") + " " + modelData.cannot
                                            color: modelData.cannot !== "" ? Theme.change : modelData.muted ? Theme.muted : Theme.ink
                                            font.pixelSize: Theme.text_sm
                                        }

                                        // What the last sync of this subtitle found, kept by the run.
                                        UiText {
                                            objectName: "syncFound"
                                            anchors.verticalCenter: parent.verticalCenter
                                            visible: (modelData.found ?? "") !== ""
                                            text: modelData.found ?? ""
                                            color: modelData.review ? Theme.change : Theme.faint
                                            font.pixelSize: Theme.text_xs
                                        }
                                    }
                                }

                                UiText {
                                    objectName: "fileReference_" + file.index
                                    visible: (file.modelData.reference ?? "") !== ""
                                    text: file.modelData.reference ?? ""
                                    color: Theme.faint
                                    font.pixelSize: Theme.text_xs
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
