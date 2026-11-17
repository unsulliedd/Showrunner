import QtQuick
import Showrunner

// A rule in words: each part is plain text, or a code (a language, a codec, a name) drawn as a badge.
Flow {
    id: sentence

    property var parts: []

    spacing: Theme.space_sm

    Repeater {
        model: sentence.parts

        delegate: Item {
            required property var modelData

            implicitWidth: modelData.code ? badge.implicitWidth : word.implicitWidth
            implicitHeight: Theme.row_sm

            CodeBadge {
                id: badge

                anchors.verticalCenter: parent.verticalCenter
                visible: modelData.code
                code: modelData.text
            }

            UiText {
                id: word

                anchors.verticalCenter: parent.verticalCenter
                visible: !modelData.code
                text: modelData.text
                font.weight: Font.Medium
            }
        }
    }
}
