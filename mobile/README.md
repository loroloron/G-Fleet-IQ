# G Fleet IQ mobile app

This is a native React Native app for G Fleet IQ dispatchers and account owners. It signs in to the live Django API, stores the session token in the device's encrypted secure storage, shows fleet and load summaries, assigns available loads, and marks assigned loads delivered. The API applies the same account and client-company access rules as the website.

## Preview on a phone

1. Install the current Node.js LTS release on the development computer.
2. In a terminal, open this `mobile` folder and run `npm install`.
3. Run `npx expo start` and scan its QR code with Expo Go.

The app connects to `https://g-fleet-iq.onrender.com` by default. Set `EXPO_PUBLIC_API_URL` only when you want to connect it to another server.

## Store builds

Expo Application Services (EAS) builds the Android and iOS app binaries in the cloud. A production build still needs the owner's Play Console and Apple Developer accounts, final app icon/screenshots, store descriptions, privacy information, and review. Do not put account passwords or signing keys in this folder.
