import {createApp} from 'vue'
import '@radix-ui/colors/slate.css'
import '@radix-ui/colors/cyan.css'
import '@radix-ui/colors/teal.css'
import '@radix-ui/colors/amber.css'
import '@radix-ui/colors/red.css'
import '@radix-ui/colors/indigo.css'
import '../styles/tokens.css'
import './demo.css'
import DemoApp from './DemoApp.vue'

createApp(DemoApp).mount('#app')
