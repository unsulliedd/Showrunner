import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// One track signature of a batch as a row of fixed columns: the check box keeps or drops the track in every file (adds
// a paired file), the badge opens the language picker, D and F set the flags, and the button at the end folds the row
// open to list each file's name for the track, then the files that lack it. Only the check box keeps or drops: the rest
// of the row does nothing, so a near miss on the button cannot drop a track in every file. `chip` is a header from the
// controller; `namesOpen`, `rows` and `missing` say whether the place has it open and what it lists. An open row grows
// taller inside its own frame, up to `names_height` where the list scrolls, and never wider: a long line is cut short.
// `form` is "row" on Overview, "lines" where Overview's box is narrow (the count, the mark and the name on a second
// line), and "label" beside the strip of the Tracks place, with the grip at its left and the name under the codec;
// `brief` takes the label's short form.
// A track without a name has a line per file that a click keeps or drops in that file alone (the file's own choice);
// where the tracks carry several names, each name is a line of its own that a click keeps or drops (a rule by name
// ahead of the row's choice). The list is one tab stop, Up and Down move along it and Space or Return acts.
Item {
    id: control

    required property var chip
    property bool namesOpen: false
    property var rows: []
    property string missing: ""
    // Why the plan keeps the track in some files though it is dropped; shown above the names, where it is seen first.
    property string held: ""
    property string form: "row"
    property bool brief: false
    // The length of one place of the grip, which moves the row up or down among the rows of its kind.
    property real gripStep: height
    readonly property alias grip: grip
    readonly property bool dropped: chip.state === "dropped"
    readonly property bool paired: chip.paired
    readonly property bool label: form === "label"
    readonly property bool clickable: rows.some(row => row.clickable)
    // What the row says after the codec: the name, or what a tick does to a paired file nobody adds yet.
    readonly property string nameText: chip.state === "paired" ? Strings.t("tracks.paired_add") : chip.name
    readonly property color textTone: dropped ? Theme.drop : Theme.ink

    signal namesToggled

    objectName: "chip" + chip.id
    implicitHeight: body.height + (namesOpen ? Theme.space_sm + foldout.height + Theme.space_md : 0)

    // The "Files ⌄" button at the end of an Overview row, behind a hairline.
    component FilesButton: AbstractButton {
        id: files

        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        leftPadding: Theme.space_md
        rightPadding: Theme.space_md
        Accessible.role: Accessible.Button
        Accessible.name: Strings.t(control.namesOpen ? "tracks.names.close" : "tracks.names.open")
        ToolTip.visible: hovered
        ToolTip.text: Accessible.name
        onClicked: control.namesToggled()

        background: Rectangle {
            radius: Theme.radius_sm
            color: files.hovered ? Theme.panel_3 : "transparent"
            border.width: files.visualFocus ? Theme.stroke : 0
            border.color: Theme.control
        }

        contentItem: RowLayout {
            spacing: Theme.space_xs

            UiText {
                Layout.fillWidth: true
                text: Strings.t(control.namesOpen ? "tracks.names.collapse" : "tracks.names.expand")
                color: control.namesOpen ? Theme.ink : Theme.muted
                font.pixelSize: Theme.text_sm
            }

            Icon {
                name: control.namesOpen ? "up" : "down"
                size: Theme.icon_sm
                color: Theme.muted
            }
        }
    }

    // D and F in a column of their own, as wide as both, so the flags of a kind's rows stand one under the other.
    component Flags: Row {
        spacing: Theme.space_xs
        // Hidden on a dropped track and on a paired file nobody adds, but kept in place.
        opacity: control.dropped || !control.chip.flags ? 0 : 1

        FlagButton {
            objectName: "defaultFlag"
            side: control.label ? Theme.pill : Theme.row_sm
            enabled: parent.opacity > 0
            flag: "default"
            on: control.chip.default
            held: control.chip.default_held
            onClicked: app.toggle_flag(control.chip.id, "default")
        }

        FlagButton {
            side: control.label ? Theme.pill : Theme.row_sm
            // An audio track has no forced flag; its place stays empty.
            opacity: control.chip.kind === "subtitle" ? 1 : 0
            enabled: parent.opacity > 0 && opacity > 0
            flag: "forced"
            on: control.chip.forced
            held: control.chip.forced_held
            onClicked: app.toggle_flag(control.chip.id, "forced")
        }
    }

    component Codec: UiText {
        text: control.chip.title
        color: control.textTone
        font.strikeout: control.dropped
        font.weight: Font.Medium
    }

    component Name: UiText {
        visible: text !== ""
        color: control.dropped ? Theme.drop : control.chip.state === "paired" ? Theme.faint : Theme.muted
        font.strikeout: control.dropped
        font.pixelSize: Theme.text_sm
    }

    component Count: UiText {
        visible: control.chip.count !== ""
        text: control.chip.count
        color: Theme.change
        font.pixelSize: Theme.text_sm
    }

    Rectangle {
        anchors.fill: parent
        visible: !control.paired || control.chip.state === "added"
        radius: Theme.radius_md
        color: control.dropped ? Theme.drop_soft : Theme.panel_2
        border.width: keep.visualFocus ? Theme.stroke : 0
        border.color: Theme.control
    }

    DashedFrame {
        anchors.fill: parent
        visible: control.paired && control.chip.state !== "added"
        radius: Theme.radius_md
        stroke: keep.visualFocus ? Theme.control : Theme.line_strong
    }

    // The row's frame takes a click that lands on it outside its controls, so none reaches what lies behind.
    MouseArea {
        anchors.fill: parent
    }

    // The row's line, or two: what lies outside the check box, the badge, the flags and the button does nothing.
    Item {
        id: body

        objectName: "chipHeader"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: control.form === "lines" ? Theme.row_lg + Theme.row_sm : Theme.row_lg

        RowLayout {
            id: line

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: Theme.row_lg
            anchors.leftMargin: control.label ? Theme.space_xs : Theme.space_md
            anchors.rightMargin: control.label ? Theme.space_xs : 0
            // Closer in the label, whose room beside the strip is fixed.
            spacing: control.label ? Theme.space_sm : Theme.space_md

            Grip {
                id: grip

                objectName: "trackGrip"
                Layout.preferredHeight: Theme.row_lg - 2 * Theme.space_xs
                visible: control.label
                // Kept in the layout where there is nothing to move, so every row's box stands at the same place.
                opacity: control.chip.movable ? 1 : 0
                enabled: control.chip.movable
                vertical: true
                step: control.gripStep
                label: Strings.f("tracks.order.card", {"track": control.chip.code + " " + control.chip.title})
            }

            Tick {
                id: keep

                objectName: "keepBox"
                ticked: control.chip.state === "kept" || control.chip.state === "added"
                adding: control.chip.state === "paired"
                tone: control.paired ? Theme.add : Theme.control
                mark: control.paired ? Theme.ground : Theme.control_ink
                label: [control.chip.code, control.chip.title, control.chip.name, control.chip.button,
                        control.chip.from || control.chip.over || ""].join(" ")
                onFlipped: app.toggle_keep(control.chip.id)
            }

            CodeBadge {
                objectName: "chipBadge"
                code: control.chip.code
                look: control.chip.state
                changed: control.chip.language_set !== ""
                pickable: true
                onPicked: app.pick_language(control.chip.id)
            }

            // The Overview row: the codec in a column of its own, the name taking the rest, then the count and the mark.
            Codec {
                Layout.preferredWidth: Theme.track_title_width
                Layout.fillWidth: control.form === "lines"
                visible: !control.label
            }

            Name {
                Layout.fillWidth: true
                visible: control.form === "row" && text !== ""
                text: control.nameText
            }

            Item {
                Layout.fillWidth: true
                visible: control.form === "row" && control.nameText === ""
            }

            Count {
                Layout.maximumWidth: implicitWidth
                visible: control.form === "row" && text !== ""
            }

            PlaceMark {
                objectName: "placeMark"
                Layout.maximumWidth: Theme.track_mark_width
                visible: control.form === "row" && text !== "" || control.label && !control.brief && text !== ""
                horizontalAlignment: Text.AlignRight
                choice: control.chip
                brief: control.label
            }

            // The label beside the strip: the codec, and under it the name with what some files lack.
            ColumnLayout {
                Layout.fillWidth: true
                visible: control.label
                spacing: 0

                Codec {
                    objectName: "labelCodec"
                    Layout.fillWidth: true
                    font.pixelSize: Theme.text_sm
                }

                // The short form says the first of the mark, the count and the name, each in its own colour.
                Name {
                    objectName: "labelName"
                    Layout.fillWidth: true
                    font.pixelSize: Theme.text_xs
                    color: !control.brief || control.dropped ? (control.dropped ? Theme.drop : Theme.muted)
                         : control.chip.short !== "" ? (control.chip.over ? Theme.control : Theme.faint)
                         : control.chip.count !== "" ? Theme.change : Theme.muted
                    text: control.brief
                          ? control.chip.short || control.chip.count || control.nameText
                          : [control.nameText, control.chip.count].filter(part => part !== "")
                                .join(" " + Strings.t("status.separator") + " ")
                }
            }

            Flags {}

            Rectangle {
                Layout.preferredWidth: Theme.stroke
                Layout.fillHeight: true
                Layout.topMargin: Theme.space_md
                Layout.bottomMargin: Theme.space_md
                visible: !control.label
                color: Theme.line
            }

            FilesButton {
                objectName: "namesButton"
                Layout.preferredWidth: Theme.track_files_width
                Layout.fillHeight: true
                Layout.topMargin: Theme.space_xs
                Layout.bottomMargin: Theme.space_xs
                visible: !control.label
                // Kept in place where there is nothing to list, so the flags stand in their column.
                opacity: control.chip.names ? 1 : 0
                enabled: control.chip.names
            }

            IconButton {
                objectName: "namesButton"
                implicitWidth: Theme.pill
                implicitHeight: Theme.pill
                visible: control.label
                opacity: control.chip.names ? 1 : 0
                enabled: control.chip.names
                iconName: control.namesOpen ? "up" : "down"
                label: Strings.t(control.namesOpen ? "tracks.names.close" : "tracks.names.open")
                tip: Strings.t("tip.names_open")
                active: control.namesOpen
                onClicked: control.namesToggled()
            }
        }

        // The second line of a narrow Overview row, under the codec: the count, the mark, then the name, cut at its end.
        RowLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: Theme.space_md
            anchors.rightMargin: Theme.space_md
            height: Theme.row_sm
            visible: control.form === "lines"
            spacing: Theme.space_md

            Count {
                Layout.maximumWidth: implicitWidth
            }

            PlaceMark {
                Layout.maximumWidth: implicitWidth
                choice: control.chip
            }

            Name {
                Layout.fillWidth: true
                text: control.nameText
            }
        }
    }

    Item {
        id: foldout

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: body.bottom
        anchors.topMargin: Theme.space_sm
        anchors.leftMargin: Theme.space_md
        anchors.rightMargin: Theme.space_md
        visible: control.namesOpen
        height: Math.min(list.contentHeight, Theme.names_height)

        ListView {
            id: list

            objectName: "chipNameRows"
            anchors.fill: parent
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            // A count, not the lines: a new plan of the same batch then updates the delegates in place.
            model: control.namesOpen ? control.rows.length : 0
            ScrollBar.vertical: Scroller {}
            Accessible.role: Accessible.List
            activeFocusOnTab: control.clickable
            Keys.onSpacePressed: toggleCurrent()
            Keys.onReturnPressed: toggleCurrent()
            Keys.onEnterPressed: toggleCurrent()

            function toggleRow(row) {
                if (row.file !== "")
                    app.toggle_file_track(control.chip.id, row.file)
                else
                    app.toggle_name(control.chip.id, row.name)
            }

            function toggleCurrent() {
                const row = control.rows[currentIndex]
                if (row && row.clickable)
                    toggleRow(row)
            }

            // The wheel over a list that scrolls moves only the list, also at its ends; the tracks box behind it
            // scrolls with the wheel anywhere else, and over a list that fits.
            WheelHandler {
                enabled: list.contentHeight > list.height
                onWheel: event => {
                    const step = event.pixelDelta.y !== 0 ? event.pixelDelta.y : event.angleDelta.y / 2
                    list.contentY = Math.max(0, Math.min(list.contentHeight - list.height, list.contentY - step))
                }
            }
            Accessible.name: Strings.t("tracks.names.open")

            delegate: Item {
                id: entry

                required property int index
                readonly property var row: control.rows[index] ?? ({"text": "", "name": "", "file": "", "clickable": false, "dropped": false, "from": "", "over": "", "short": "", "label": "", "divider": false})
                readonly property bool current: ListView.isCurrentItem && list.activeFocus && row.clickable

                objectName: "chipNameRow"
                width: list.width - Theme.scroll_thumb - Theme.space_sm
                height: Theme.row_sm
                Accessible.role: row.clickable ? Accessible.Button : Accessible.StaticText
                Accessible.name: row.label

                Rectangle {
                    anchors.fill: parent
                    visible: entry.row.clickable && (hover.hovered || entry.current)
                    radius: Theme.radius_sm
                    color: hover.hovered ? Theme.panel_3 : "transparent"
                    border.width: entry.current ? Theme.stroke : 0
                    border.color: Theme.control
                }

                // A season's divider: its name between two rules.
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.space_sm
                    anchors.rightMargin: Theme.space_sm
                    visible: entry.row.divider
                    spacing: Theme.space_sm

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: Theme.stroke
                        color: Theme.line
                    }

                    UiText {
                        text: entry.row.text
                        color: Theme.muted
                        font.pixelSize: Theme.text_xs
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: Theme.stroke
                        color: Theme.line
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.space_sm
                    anchors.rightMargin: Theme.space_sm
                    visible: !entry.row.divider
                    spacing: Theme.space_md

                    UiText {
                        Layout.fillWidth: true
                        text: entry.row.text
                        mono: true
                        color: entry.row.dropped ? Theme.drop : Theme.ink
                        font.strikeout: entry.row.dropped
                    }

                    PlaceMark {
                        objectName: "nameMark"
                        Layout.maximumWidth: implicitWidth
                        choice: entry.row
                    }

                    // The line's own keep or drop control: what a click on the line does next.
                    Icon {
                        visible: entry.row.clickable
                        name: entry.row.dropped ? "x" : "check"
                        size: Theme.icon_sm
                        color: entry.row.dropped ? Theme.drop : Theme.faint
                    }
                }

                HoverHandler {
                    id: hover

                    enabled: entry.row.clickable
                    cursorShape: Qt.PointingHandCursor
                }

                TapHandler {
                    enabled: entry.row.clickable
                    onTapped: {
                        list.currentIndex = entry.index
                        list.toggleRow(entry.row)
                    }
                }
            }

            header: Item {
                width: list.width - Theme.scroll_thumb - Theme.space_sm
                // Sized by binding, not by a layout, so the list starts below nothing when the reason is the first thing.
                readonly property real hintHeight: control.clickable ? hint.height + Theme.space_sm : 0
                height: hintHeight + (control.held !== "" ? reason.implicitHeight + Theme.space_sm : 0)

                Row {
                    id: hint

                    visible: control.clickable
                    spacing: Theme.space_md

                    UiText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: Strings.t("tracks.names.hint")
                        color: Theme.muted
                        font.pixelSize: Theme.text_sm
                    }

                    HelpTip {
                        anchors.verticalCenter: parent.verticalCenter
                        topic: "names"
                    }
                }

                UiText {
                    id: reason

                    anchors.left: parent.left
                    anchors.right: parent.right
                    y: parent.hintHeight
                    visible: control.held !== ""
                    text: control.held
                    color: Theme.change
                    font.pixelSize: Theme.text_sm
                    wrapMode: Text.WordWrap
                }
            }

            footer: Item {
                width: list.width - Theme.scroll_thumb - Theme.space_sm
                height: control.missing !== "" ? note.implicitHeight + Theme.space_sm : 0

                UiText {
                    id: note

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    visible: control.missing !== ""
                    text: control.missing
                    color: Theme.change
                    font.pixelSize: Theme.text_sm
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}
