import React from "react";
import {
  SafeAreaView,
  StatusBar,
  Platform,
  View,
  ViewStyle,
} from "react-native";

export function Screen({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: ViewStyle;
}) {
  return (
    <SafeAreaView
      style={{
        flex: 1,
        backgroundColor: "#fff",
        paddingTop: Platform.OS === "android" ? StatusBar.currentHeight : 0,
      }}
    >
      {/* This inner container creates the “border/gutter” and centers content */}
      <View
        style={[
          {
            flex: 1,
            paddingHorizontal: 22,
            paddingTop: 18,
            paddingBottom: 22,
            width: "100%",
            maxWidth: 520,
            alignSelf: "center",
          },
          style,
        ]}
      >
        {children}
      </View>
    </SafeAreaView>
  );
}
